"""POST /detect — реальный inference на deployed prod-моделях (Phase 9).

Pipeline на скриншоте:
  1. Получаем screenshot row → screen_paths[monitor_index] = s3:// URL.
  2. Достаём текущие prod-модели localize + tumor (промоут через
     /admin/models/{id}/promote; на запрос берётся последняя prod).
  3. Скачиваем PNG скриншота, гоним через localize → список регионов
     (отсортирован по confidence убыванию).
  4. Для каждого региона: INSERT `localize_detections` с confidence; режем
     crop, заливаем в S3, создаём `localize_images` (с detection_id, без
     annotation_id — annotation появится при последующем submit/approve);
     если tumor-модель задеплоена, гоним crop через tumor → INSERT
     `tumor_detections` с confidence. Tumor.bbox в `tumor_detections` —
     в crop-пространстве; в API-ответе уже переведён в screen-пространство
     для удобства клиента.
  5. Ответ — DetectResponse.regions = [RegionPrediction(region, tumor?)],
     причём оба BBoxResult несут `detection_id`. Клиент использует эти ID
     в batch-`/detect/annotations` при отправке confirmed/corrected.

Inference синхронный/CPU-bound — обёрнут в asyncio.to_thread внутри
services/inference.py. Веса YOLO lazy-load'ятся при первом запросе и держатся
в памяти процесса (LRU-cache). Детекции (вместе с crop'ами) пишутся в одной
транзакции вместе с inference; при любом исключении flushed-rows откатываются.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, SessionDep, StorageDep
from app.core.exceptions import AppError
from app.models.localize import LocalizeDetection
from app.models.mlops import Deployment, Model
from app.models.screenshot import Screenshot
from app.models.tumor import TumorDetection
from app.schemas.detect import (
    BBoxResult,
    DetectRequest,
    DetectResponse,
    RegionPrediction,
)
from app.services import inference
from app.services.crops import create_localize_image
from app.services.inference import predict_all

router = APIRouter(tags=["detect"])


async def _prod_model(session: AsyncSession, model_type: str) -> Model | None:
    stmt = (
        select(Model)
        .join(Deployment, Deployment.model_id == Model.id)
        .where(
            Model.model_type == model_type,
            Model.status == "prod",
            Deployment.is_active.is_(True),
        )
        .order_by(Deployment.deployed_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


@router.post("", response_model=DetectResponse)
async def detect(
    payload: DetectRequest,
    _: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> DetectResponse:
    screen = await session.get(Screenshot, payload.screenshot_id)
    if screen is None:
        raise AppError(
            f"Screenshot {payload.screenshot_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
        )

    screen_url = (screen.screen_paths or {}).get(str(payload.monitor_index))
    if not screen_url:
        raise AppError(
            f"No image for monitor {payload.monitor_index} in screenshot",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
        )

    loc_model = await _prod_model(session, "localize")
    if loc_model is None:
        # Localize обязателен — без него pipeline не начинается.
        raise AppError(
            "No localize model deployed",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="no_model_deployed",
        )
    tum_model = await _prod_model(session, "tumor")

    u = urlparse(screen_url)
    image_bytes = await storage.download_bytes(
        bucket=u.netloc, key=u.path.lstrip("/")
    )

    regions = await predict_all(
        str(loc_model.id), loc_model.artifact_path, image_bytes
    )

    predictions: list[RegionPrediction] = []
    for region in regions:
        region_bbox = {k: region[k] for k in ("x", "y", "w", "h")}

        # Phase 10: персистим детекцию + localize_image + (опц.) tumor_detection.
        loc_det = LocalizeDetection(
            screen_id=screen.id,
            model_id=loc_model.id,
            monitor_index=payload.monitor_index,
            bbox=region_bbox,
            confidence=region["confidence"],
        )
        session.add(loc_det)
        await session.flush()  # нужен loc_det.id для localize_images.detection_id

        loc_img = await create_localize_image(
            session,
            storage,
            screen=screen,
            monitor_index=payload.monitor_index,
            bbox=region_bbox,
            image_bytes=image_bytes,
            detection_id=loc_det.id,
            annotation_id=None,
        )
        await session.flush()  # для tumor_detections.localize_image_id

        tumor_result: BBoxResult | None = None
        if tum_model is not None:
            crop_bytes = inference.crop_png(image_bytes, region_bbox)
            tumor_in_crop_list = await predict_all(
                str(tum_model.id), tum_model.artifact_path, crop_bytes
            )
            if tumor_in_crop_list:
                # Top-1 опухоль на регион (см. inference.py: список уже отсортирован).
                top = tumor_in_crop_list[0]
                tum_det = TumorDetection(
                    localize_image_id=loc_img.id,
                    model_id=tum_model.id,
                    # bbox хранится в crop-пространстве (см. schema docstring).
                    bbox={k: top[k] for k in ("x", "y", "w", "h")},
                    confidence=top["confidence"],
                )
                session.add(tum_det)
                await session.flush()  # нужен tum_det.id для API-ответа

                # API-ответ: координаты в screen-space (сдвиг на region.x/y).
                tumor_result = BBoxResult(
                    x=region_bbox["x"] + top["x"],
                    y=region_bbox["y"] + top["y"],
                    w=top["w"],
                    h=top["h"],
                    confidence=top["confidence"],
                    detection_id=tum_det.id,
                )

        predictions.append(
            RegionPrediction(
                region=BBoxResult(
                    **region_bbox,
                    confidence=region["confidence"],
                    detection_id=loc_det.id,
                ),
                tumor=tumor_result,
            )
        )

    await session.commit()

    return DetectResponse(
        screenshot_id=payload.screenshot_id,
        monitor_index=payload.monitor_index,
        localize_model_version=loc_model.version,
        tumor_model_version=tum_model.version if tum_model else None,
        regions=predictions,
    )
