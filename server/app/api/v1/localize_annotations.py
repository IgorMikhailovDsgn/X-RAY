from fastapi import APIRouter, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.models.localize import LocalizeAnnotation
from app.schemas.common import BBox
from app.schemas.localize import LocalizeAnnotationCreate, LocalizeAnnotationResponse

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
    annotation = LocalizeAnnotation(
        screen_id=payload.screen_id,
        detection_id=payload.detection_id,
        monitor_index=payload.monitor_index,
        bbox=bbox_payload,
        action=payload.action,
        annotator_id=str(user.id),
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
    )
