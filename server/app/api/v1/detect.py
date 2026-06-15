"""POST /detect — реальный inference на deployed prod-моделях (Phase 9).

Pipeline на скриншоте:
  1. Получаем screenshot row → screen_paths[monitor_index] = s3:// URL.
  2. Достаём текущие prod-модели localize + tumor (промоут через
     /admin/models/{id}/promote; на запрос берётся последняя prod).
  3. Скачиваем PNG скриншота, гоним через localize → список регионов
     (отсортирован по confidence убыванию).
  4. Для каждого региона — если tumor-модель есть, кропаем и гоним tumor;
     tumor.x/y из crop-пространства переводятся обратно в координаты
     исходного скрина (сдвиг на region.x/y).
  5. Ответ — DetectResponse.regions = [RegionPrediction(region, tumor?)].

Inference синхронный/CPU-bound — обёрнут в asyncio.to_thread внутри
services/inference.py. Веса YOLO lazy-load'ятся при первом запросе и держатся
в памяти процесса (LRU-cache).
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, SessionDep, StorageDep
from app.core.exceptions import AppError
from app.models.mlops import Deployment, Model
from app.models.screenshot import Screenshot
from app.schemas.detect import BBoxResult, DetectRequest, DetectResponse, RegionPrediction
from app.services.inference import crop_png, predict_all

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
        tumor_result: BBoxResult | None = None
        if tum_model is not None:
            crop_bytes = crop_png(image_bytes, region)
            tumor_in_crop = await predict_all(
                str(tum_model.id), tum_model.artifact_path, crop_bytes
            )
            if tumor_in_crop:
                # Берём top-1 опухоль на регион — обычно их 0-1, а если YOLO
                # дала несколько кандидатов, top-confidence — самый честный
                # сигнал. Координаты из crop-пространства → в координаты
                # исходного скрина (сдвиг на region.x/y).
                top = tumor_in_crop[0]
                tumor_result = BBoxResult(
                    x=region["x"] + top["x"],
                    y=region["y"] + top["y"],
                    w=top["w"],
                    h=top["h"],
                    confidence=top["confidence"],
                )
        predictions.append(RegionPrediction(
            region=BBoxResult(**region),
            tumor=tumor_result,
        ))

    return DetectResponse(
        screenshot_id=payload.screenshot_id,
        monitor_index=payload.monitor_index,
        localize_model_version=loc_model.version,
        tumor_model_version=tum_model.version if tum_model else None,
        regions=predictions,
    )
