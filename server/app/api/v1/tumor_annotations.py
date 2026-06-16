from fastapi import APIRouter, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.core.exceptions import ValidationAppError
from app.models.tumor import TumorAnnotation, TumorDetection
from app.schemas.common import BBox
from app.schemas.tumor import TumorAnnotationCreate, TumorAnnotationResponse
from app.services.corrections import compute_signals

router = APIRouter(tags=["tumor"])


@router.post(
    "",
    response_model=TumorAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tumor_annotation(
    payload: TumorAnnotationCreate,
    session: SessionDep,
    user: CurrentUser,
) -> TumorAnnotationResponse:
    bbox_payload = payload.bbox.model_dump() if payload.bbox is not None else None

    detection_bbox: dict | None = None
    detection_confidence: float | None = None
    if payload.detection_id is not None:
        det = await session.get(TumorDetection, payload.detection_id)
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

    annotation = TumorAnnotation(
        localize_image_id=payload.localize_image_id,
        detection_id=payload.detection_id,
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
    return TumorAnnotationResponse(
        id=annotation.id,
        localize_image_id=annotation.localize_image_id,
        detection_id=annotation.detection_id,
        bbox=BBox(**annotation.bbox) if annotation.bbox else None,
        action=annotation.action,  # type: ignore[arg-type]
        annotator_id=annotation.annotator_id,
        annotated_at=annotation.annotated_at,
        correction_type=annotation.correction_type,
        iou_with_detection=annotation.iou_with_detection,
        training_weight=annotation.training_weight,
    )
