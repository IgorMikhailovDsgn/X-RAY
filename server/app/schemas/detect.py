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
    # ID соответствующей `*_detections` строки. nullable — на случай редкого
    # сценария, когда INSERT детекции откатился (исторически — старые клиенты).
    # Клиент использует это поле в batch-`/detect/annotations` при отправке
    # confirmed/corrected.
    detection_id: uuid.UUID | None = None


class RegionPrediction(BaseModel):
    """Один найденный регион + опциональная вложенная опухоль.

    `tumor.x/y` — в координатах исходного скрина (уже сдвинуто на region.x/y),
    не в crop-пространстве. Если tumor-модель не задеплоена либо ничего не
    нашла в crop'е этого региона — `tumor=None`.
    """

    region: BBoxResult
    tumor: BBoxResult | None = None


class DetectResponse(BaseModel):
    screenshot_id: uuid.UUID
    monitor_index: int
    localize_model_version: str | None = None
    tumor_model_version: str | None = None
    # Все найденные регионы (отсортированы по confidence убыванию). Пустой
    # список = модель отработала, регионов не нашла.
    regions: list[RegionPrediction] = []
