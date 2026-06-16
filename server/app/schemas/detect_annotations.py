"""Pydantic-схемы для `POST /api/v1/detect/annotations` (Phase 10 batch).

Один POST = вся «сессия» аннотаций одного screen'а атомарно. Используется
после `/detect` (Approve/Edit), плюс может использоваться cold-start
Annotate-flow'ом (тогда detection_id у всех items = None).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import BBox
from app.schemas.localize import LocalizeAnnotationResponse
from app.schemas.tumor import TumorAnnotationResponse

Action = Literal["confirmed", "corrected", "created"]


class LocalizeBatchItem(BaseModel):
    """Одна region-аннотация в batch'е.

    Координатная конвенция bbox — screen-space физ. пиксели (как в
    localize_detections.bbox / localize_annotations.bbox).
    """

    detection_id: uuid.UUID | None = None
    monitor_index: int = Field(ge=0)
    bbox: BBox | None = None
    action: Action


class TumorBatchItem(BaseModel):
    """Одна tumor-аннотация в batch'е.

    Координатная конвенция bbox — crop-space (привязка к region'у через
    `region_index` в массиве `localize[]` этого же запроса).
    """

    region_index: int = Field(ge=0)
    detection_id: uuid.UUID | None = None
    bbox: BBox | None = None
    action: Action


class BatchAnnotationsRequest(BaseModel):
    """Все аннотации одного screenshot'а в одном transaction'е.

    Cascade-валидация: если `localize[i].action='corrected' + bbox=NULL` (Mark
    Null Region) или `localize[i].action='created' + bbox=NULL` — то tumor-items
    с `region_index=i` не допускаются (нет региона = нет crop'а для опухоли).
    Сервер возвращает 422.
    """

    screen_id: uuid.UUID
    localize: list[LocalizeBatchItem]
    tumors: list[TumorBatchItem] = Field(default_factory=list)


class BatchAnnotationsResponse(BaseModel):
    localize: list[LocalizeAnnotationResponse]
    tumors: list[TumorAnnotationResponse]
