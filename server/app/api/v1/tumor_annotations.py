from fastapi import APIRouter, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.models.tumor import TumorAnnotation
from app.schemas.common import BBox
from app.schemas.tumor import TumorAnnotationCreate, TumorAnnotationResponse

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
    annotation = TumorAnnotation(
        localize_image_id=payload.localize_image_id,
        detection_id=payload.detection_id,
        bbox=bbox_payload,
        action=payload.action,
        annotator_id=str(user.id),
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
    )
