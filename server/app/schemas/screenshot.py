import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ScreenshotMeta(BaseModel):
    device_id: str = Field(min_length=1)
    monitor_count: int = Field(ge=1)
    captured_at: datetime | None = None


class ScreenshotResponse(BaseModel):
    id: uuid.UUID
    captured_at: datetime
    monitor_count: int
    screen_paths: dict[str, str]
