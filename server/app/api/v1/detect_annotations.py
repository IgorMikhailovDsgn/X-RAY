"""POST /api/v1/detect/annotations — атомарный batch (Phase 10).

Принимает все аннотации одной detect-сессии (region + tumor) и пишет в одной
транзакции. По сравнению с N отдельными POST'ами в `/localize-annotations` /
`/tumor-annotations`:

- Нет partial-state: либо всё сохранилось, либо ничего.
- Один round-trip для типичной сессии (~3-6 запросов сжимаются в один).
- Cascade-валидация: tumor нельзя привязать к Mark-Null-региону.
- Crop'ы для новых регионов (без detection_id, action='created') режутся на
  сервере — клиенту не нужно дублировать crop-логику.

Старые per-item эндпоинты не убираем — sync-queue (оффлайн) пока работает
через них.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, SessionDep, StorageDep
from app.core.exceptions import ValidationAppError
from app.models.localize import LocalizeAnnotation, LocalizeDetection, LocalizeImage
from app.models.screenshot import Screenshot
from app.models.tumor import TumorAnnotation, TumorDetection
from app.schemas.common import BBox
from app.schemas.detect_annotations import (
    BatchAnnotationsRequest,
    BatchAnnotationsResponse,
)
from app.schemas.localize import LocalizeAnnotationResponse
from app.schemas.tumor import TumorAnnotationResponse
from app.services.corrections import compute_signals
from app.services.crops import create_localize_image
from app.storage import S3Client

router = APIRouter(tags=["detect"])


@router.post(
    "",
    response_model=BatchAnnotationsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def batch_create_annotations(
    payload: BatchAnnotationsRequest,
    session: SessionDep,
    storage: StorageDep,
    user: CurrentUser,
) -> BatchAnnotationsResponse:
    # 0. Валидация: screen существует, monitor_index согласован.
    screen = await session.get(Screenshot, payload.screen_id)
    if screen is None:
        raise ValidationAppError(
            "screen_id not found", details={"screen_id": str(payload.screen_id)}
        )

    # 1. Pydantic + локальная cascade-валидация.
    _validate_cascade(payload)

    # 2. Аккумуляторы для ответа + map region_index → localize_image_id (нужен
    # tumor'ам для FK).
    loc_responses: list[LocalizeAnnotationResponse] = []
    region_to_loc_image: dict[int, uuid.UUID] = {}

    # 3. Image PNG скриншота нужен только если придётся резать crop'ы для новых
    # регионов (action='created' с bbox). Загружаем лениво.
    _image_bytes_cache: dict[int, bytes] = {}

    async def _get_screen_bytes(monitor_index: int) -> bytes:
        if monitor_index in _image_bytes_cache:
            return _image_bytes_cache[monitor_index]
        screen_url = (screen.screen_paths or {}).get(str(monitor_index))
        if not screen_url:
            raise ValidationAppError(
                f"No image for monitor {monitor_index} in screen_paths"
            )
        u = urlparse(screen_url)
        data = await storage.download_bytes(bucket=u.netloc, key=u.path.lstrip("/"))
        _image_bytes_cache[monitor_index] = data
        return data

    # 4. Обрабатываем localize-items в порядке.
    for region_index, item in enumerate(payload.localize):
        loc_ann, loc_img = await _insert_localize_item(
            session,
            storage,
            screen=screen,
            user_id=str(user.id),
            item=item,
            get_screen_bytes=_get_screen_bytes,
        )
        loc_responses.append(_loc_response(loc_ann))
        if loc_img is not None:
            region_to_loc_image[region_index] = loc_img.id

    # 5. Tumor-items.
    tum_responses: list[TumorAnnotationResponse] = []
    for t_item in payload.tumors:
        loc_image_id = region_to_loc_image.get(t_item.region_index)
        if loc_image_id is None:
            # _validate_cascade'у должно было поймать. Защитная страховка.
            raise ValidationAppError(
                f"tumor.region_index={t_item.region_index} has no localize_image",
                details={"region_index": t_item.region_index},
            )
        tum_ann = await _insert_tumor_item(
            session,
            user_id=str(user.id),
            localize_image_id=loc_image_id,
            item=t_item,
        )
        tum_responses.append(_tum_response(tum_ann))

    await session.commit()
    return BatchAnnotationsResponse(localize=loc_responses, tumors=tum_responses)


# ---------- helpers ----------


def _validate_cascade(payload: BatchAnnotationsRequest) -> None:
    """tumor.region_index должен указывать на регион, который реально
    существует на скрине. Правило:

      - action='confirmed' (с detection_id) → регион есть → tumor OK.
        Клиент шлёт bbox=None у confirmed, но крип из /detect остаётся
        валидным якорем для tumor-аннотации.
      - action='corrected'/'created' + bbox задан → регион есть → tumor OK.
      - action='corrected'/'created' + bbox=None → Mark Null:
        регион «не существует» по мнению врача → tumor НЕ OK (семантически
        опухоль не может жить в отсутствующем регионе).
    """
    n_loc = len(payload.localize)
    for i, t in enumerate(payload.tumors):
        if t.region_index >= n_loc:
            raise ValidationAppError(
                f"tumors[{i}].region_index out of range",
                details={"region_index": t.region_index, "localize_len": n_loc},
            )
        loc_item = payload.localize[t.region_index]
        region_exists = loc_item.action == "confirmed" or loc_item.bbox is not None
        if not region_exists:
            raise ValidationAppError(
                f"tumors[{i}] points to a Mark-Null region (no crop to attach to)",
                details={"region_index": t.region_index},
            )


async def _insert_localize_item(
    session: AsyncSession,
    storage: S3Client,
    *,
    screen: Screenshot,
    user_id: str,
    item,
    get_screen_bytes,
) -> tuple[LocalizeAnnotation, LocalizeImage | None]:
    """INSERT'ит одну localize_annotations + (если нужно) localize_images.

    Возвращает (annotation, localize_image|None). localize_image=None если
    регион Mark Null (bbox=None) — туда нечего крепить.
    """
    bbox_payload = item.bbox.model_dump() if item.bbox is not None else None

    detection_bbox = None
    detection_confidence = None
    if item.detection_id is not None:
        det = await session.get(LocalizeDetection, item.detection_id)
        if det is None:
            raise ValidationAppError(
                "localize detection_id not found",
                details={"detection_id": str(item.detection_id)},
            )
        detection_bbox = det.bbox
        detection_confidence = det.confidence

    final_action, ct, iou_val, weight = compute_signals(
        client_action=item.action,
        ann_bbox=bbox_payload,
        detection_bbox=detection_bbox,
        detection_confidence=detection_confidence,
        has_detection=item.detection_id is not None,
    )

    ann = LocalizeAnnotation(
        screen_id=screen.id,
        detection_id=item.detection_id,
        monitor_index=item.monitor_index,
        bbox=bbox_payload,
        action=final_action,
        annotator_id=user_id,
        correction_type=ct,
        iou_with_detection=iou_val,
        training_weight=weight,
    )
    session.add(ann)
    await session.flush()

    # Если есть detection_id — у /detect уже был создан localize_images
    # с этим detection_id (crop в S3). Переиспользуем его независимо от того,
    # есть ли у клиентской аннотации bbox: для confirmed клиент шлёт bbox=nil,
    # но crop из /detect остаётся валидным якорем для tumor-аннотаций.
    if item.detection_id is not None:
        from sqlalchemy import select

        existing = (
            await session.execute(
                select(LocalizeImage).where(
                    LocalizeImage.detection_id == item.detection_id
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return ann, existing

    # Cold-start / Mark Null без детекции: bbox=None → крепить tumor некуда.
    if bbox_payload is None:
        return ann, None

    # Cold-start с bbox: режем crop сами и создаём новый localize_image.
    image_bytes = await get_screen_bytes(item.monitor_index)
    img = await create_localize_image(
        session,
        storage,
        screen=screen,
        monitor_index=item.monitor_index,
        bbox=bbox_payload,
        image_bytes=image_bytes,
        detection_id=item.detection_id,
        annotation_id=ann.id,
    )
    await session.flush()
    return ann, img


async def _insert_tumor_item(
    session: AsyncSession,
    *,
    user_id: str,
    localize_image_id: uuid.UUID,
    item,
) -> TumorAnnotation:
    bbox_payload = item.bbox.model_dump() if item.bbox is not None else None

    detection_bbox = None
    detection_confidence = None
    if item.detection_id is not None:
        det = await session.get(TumorDetection, item.detection_id)
        if det is None:
            raise ValidationAppError(
                "tumor detection_id not found",
                details={"detection_id": str(item.detection_id)},
            )
        detection_bbox = det.bbox
        detection_confidence = det.confidence

    final_action, ct, iou_val, weight = compute_signals(
        client_action=item.action,
        ann_bbox=bbox_payload,
        detection_bbox=detection_bbox,
        detection_confidence=detection_confidence,
        has_detection=item.detection_id is not None,
    )

    ann = TumorAnnotation(
        localize_image_id=localize_image_id,
        detection_id=item.detection_id,
        bbox=bbox_payload,
        action=final_action,
        annotator_id=user_id,
        correction_type=ct,
        iou_with_detection=iou_val,
        training_weight=weight,
    )
    session.add(ann)
    await session.flush()
    return ann


def _loc_response(ann: LocalizeAnnotation) -> LocalizeAnnotationResponse:
    return LocalizeAnnotationResponse(
        id=ann.id,
        screen_id=ann.screen_id,
        detection_id=ann.detection_id,
        monitor_index=ann.monitor_index,
        bbox=BBox(**ann.bbox) if ann.bbox else None,
        action=ann.action,  # type: ignore[arg-type]
        annotator_id=ann.annotator_id,
        annotated_at=ann.annotated_at,
        correction_type=ann.correction_type,
        iou_with_detection=ann.iou_with_detection,
        training_weight=ann.training_weight,
    )


def _tum_response(ann: TumorAnnotation) -> TumorAnnotationResponse:
    return TumorAnnotationResponse(
        id=ann.id,
        localize_image_id=ann.localize_image_id,
        detection_id=ann.detection_id,
        bbox=BBox(**ann.bbox) if ann.bbox else None,
        action=ann.action,  # type: ignore[arg-type]
        annotator_id=ann.annotator_id,
        annotated_at=ann.annotated_at,
        correction_type=ann.correction_type,
        iou_with_detection=ann.iou_with_detection,
        training_weight=ann.training_weight,
    )
