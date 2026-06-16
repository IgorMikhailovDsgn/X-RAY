from fastapi import APIRouter, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.core.exceptions import ValidationAppError
from app.models.localize import LocalizeAnnotation, LocalizeDetection
from app.schemas.common import BBox
from app.schemas.localize import LocalizeAnnotationCreate, LocalizeAnnotationResponse
from app.services.corrections import compute_signals

router = APIRouter(tags=["localize"])


@router.post(
    "",
    response_model=LocalizeAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_localize_annotation(
    payload: LocalizeAnnotationCreate,
    session: SessionDep,
    user: CurrentUser,
) -> LocalizeAnnotationResponse:
    bbox_payload = payload.bbox.model_dump() if payload.bbox is not None else None

    # Phase 10: подтягиваем detection (если есть) для вычисления correction
    # сигналов. Сервер — единственная точка истины: action может быть переписан
    # с corrected на confirmed при IoU≥0.95.
    detection_bbox: dict | None = None
    detection_confidence: float | None = None
    if payload.detection_id is not None:
        det = await session.get(LocalizeDetection, payload.detection_id)
        if det is None:
            raise ValidationAppError(
                "detection_id not found",
                details={"detection_id": str(payload.detection_id)},
            )
        detection_bbox = det.bbox
        detection_confidence = det.confidence

    final_action, correction_type, iou_value, weight = compute_signals(
        client_action=payload.action,
        ann_bbox=bbox_payload,
        detection_bbox=detection_bbox,
        detection_confidence=detection_confidence,
        has_detection=payload.detection_id is not None,
    )

    annotation = LocalizeAnnotation(
        screen_id=payload.screen_id,
        detection_id=payload.detection_id,
        monitor_index=payload.monitor_index,
        bbox=bbox_payload,
        action=final_action,
        annotator_id=str(user.id),
        correction_type=correction_type,
        iou_with_detection=iou_value,
        training_weight=weight,
    )
    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)
    return LocalizeAnnotationResponse(
        id=annotation.id,
        screen_id=annotation.screen_id,
        detection_id=annotation.detection_id,
        monitor_index=annotation.monitor_index,
        bbox=BBox(**annotation.bbox) if annotation.bbox else None,
        action=annotation.action,  # type: ignore[arg-type]
        annotator_id=annotation.annotator_id,
        annotated_at=annotation.annotated_at,
        correction_type=annotation.correction_type,
        iou_with_detection=annotation.iou_with_detection,
        training_weight=annotation.training_weight,
    )
