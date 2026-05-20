import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request, status
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.api.v1.deps import CurrentUser, SessionDep, StorageDep
from app.config import settings
from app.core.exceptions import ValidationAppError
from app.models.screenshot import Screenshot
from app.schemas.screenshot import ScreenshotMeta, ScreenshotResponse

router = APIRouter(tags=["screenshots"])

_SCREEN_KEY = re.compile(r"^screen_(\d+)$")
_ALLOWED_CONTENT_TYPE = "image/png"


@router.post("", response_model=ScreenshotResponse, status_code=status.HTTP_201_CREATED)
async def upload_screenshot(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    storage: StorageDep,
    meta: str = Form(...),
) -> ScreenshotResponse:
    try:
        meta_payload = ScreenshotMeta.model_validate_json(meta)
    except ValidationError as exc:
        raise ValidationAppError(
            "Invalid meta payload", details={"errors": exc.errors()}
        ) from exc

    form = await request.form()
    files: dict[int, UploadFile] = {}
    for field_name, value in form.multi_items():
        if not isinstance(value, UploadFile):
            continue
        match = _SCREEN_KEY.match(field_name)
        if not match:
            continue
        if value.content_type != _ALLOWED_CONTENT_TYPE:
            raise ValidationAppError(
                f"{field_name} must be {_ALLOWED_CONTENT_TYPE}",
                details={"field": field_name, "content_type": value.content_type},
            )
        files[int(match.group(1))] = value

    if 0 not in files:
        raise ValidationAppError("screen_0 file is required")
    if len(files) != meta_payload.monitor_count:
        raise ValidationAppError(
            "monitor_count does not match number of uploaded files",
            details={"monitor_count": meta_payload.monitor_count, "files": len(files)},
        )

    screenshot_id = uuid.uuid4()
    screen_paths: dict[str, str] = {}
    for monitor_index, upload in sorted(files.items()):
        content = await upload.read()
        if not content:
            raise ValidationAppError(f"screen_{monitor_index} file is empty")
        key = f"{screenshot_id}/monitor_{monitor_index}.png"
        screen_paths[str(monitor_index)] = await storage.upload_bytes(
            bucket=settings.s3_bucket_screenshots,
            key=key,
            content=content,
            content_type=_ALLOWED_CONTENT_TYPE,
        )

    captured_at = meta_payload.captured_at or datetime.now(UTC)
    screenshot = Screenshot(
        id=screenshot_id,
        captured_at=captured_at,
        device_id=meta_payload.device_id,
        monitor_count=meta_payload.monitor_count,
        screen_paths=screen_paths,
    )
    session.add(screenshot)
    await session.commit()
    await session.refresh(screenshot)

    _ = user  # annotator_id не пишется в screenshots; user проверяет auth.

    return ScreenshotResponse(
        id=screenshot.id,
        captured_at=screenshot.captured_at,
        monitor_count=screenshot.monitor_count,
        screen_paths=screenshot.screen_paths,
    )
