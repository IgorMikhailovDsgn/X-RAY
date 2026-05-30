"""Pydantic-схемы для POST /detect."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class DetectRequest(BaseModel):
    screenshot_id: uuid.UUID
    monitor_index: int = Field(default=0, ge=0)


class BBoxResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)


class DetectResponse(BaseModel):
    screenshot_id: uuid.UUID
    monitor_index: int
    localize_model_version: str | None = None
    tumor_model_version: str | None = None
    # NULL = модель отработала, ничего не нашла (важно: это не ошибка).
    region: BBoxResult | None = None
    # tumor.x/y — в координатах исходного скрина (не crop'а).
    tumor: BBoxResult | None = None
