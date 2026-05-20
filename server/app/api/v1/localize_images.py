import uuid

from fastapi import APIRouter, Form, UploadFile, status
from pydantic import ValidationError

from app.api.v1.deps import CurrentUser, SessionDep, StorageDep
from app.config import settings
from app.core.exceptions import ValidationAppError
from app.models.localize import LocalizeImage
from app.schemas.common import BBox
from app.schemas.localize import LocalizeImageMeta, LocalizeImageResponse

router = APIRouter(tags=["localize"])

_ALLOWED_CONTENT_TYPE = "image/png"


@router.post("", response_model=LocalizeImageResponse, status_code=status.HTTP_201_CREATED)
async def upload_localize_image(
    session: SessionDep,
    user: CurrentUser,
    storage: StorageDep,
    meta: str = Form(...),
    crop: UploadFile = Form(...),
) -> LocalizeImageResponse:
    try:
        meta_payload = LocalizeImageMeta.model_validate_json(meta)
    except ValidationError as exc:
        raise ValidationAppError(
            "Invalid meta payload", details={"errors": exc.errors()}
        ) from exc

    if crop.content_type != _ALLOWED_CONTENT_TYPE:
        raise ValidationAppError(
            f"crop must be {_ALLOWED_CONTENT_TYPE}",
            details={"content_type": crop.content_type},
        )

    content = await crop.read()
    if not content:
        raise ValidationAppError("crop file is empty")

    image_id = uuid.uuid4()
    key = f"{image_id}.png"
    localize_path = await storage.upload_bytes(
        bucket=settings.s3_bucket_localize,
        key=key,
        content=content,
        content_type=_ALLOWED_CONTENT_TYPE,
    )

    record = LocalizeImage(
        id=image_id,
        screen_id=meta_payload.screen_id,
        detection_id=meta_payload.detection_id,
        annotation_id=meta_payload.annotation_id,
        monitor_index=meta_payload.monitor_index,
        bbox=meta_payload.bbox.model_dump(),
        localize_path=localize_path,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    _ = user

    return LocalizeImageResponse(
        id=record.id,
        screen_id=record.screen_id,
        detection_id=record.detection_id,
        annotation_id=record.annotation_id,
        monitor_index=record.monitor_index,
        bbox=BBox(**record.bbox),
        localize_path=record.localize_path,
        created_at=record.created_at,
    )
