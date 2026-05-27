import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ScreenshotMeta(BaseModel):
    # device_id попадает в S3-ключ (см. screenshots.py). Запрещаем "/", "..",
    # пробелы и спецсимволы — иначе можно вылезти из префикса бакета.
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    monitor_count: int = Field(ge=1)
    captured_at: datetime | None = None


class ScreenshotResponse(BaseModel):
    id: uuid.UUID
    captured_at: datetime
    monitor_count: int
    screen_paths: dict[str, str]
