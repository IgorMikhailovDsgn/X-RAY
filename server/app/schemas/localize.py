import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import BBox

LocalizeAction = Literal["confirmed", "corrected", "created"]


class LocalizeImageMeta(BaseModel):
    screen_id: uuid.UUID
    detection_id: uuid.UUID | None = None
    annotation_id: uuid.UUID | None = None
    monitor_index: int = Field(ge=0)
    bbox: BBox

    @model_validator(mode="after")
    def _check_source(self) -> "LocalizeImageMeta":
        if self.detection_id is None and self.annotation_id is None:
            raise ValueError("detection_id or annotation_id is required")
        return self


class LocalizeImageResponse(BaseModel):
    id: uuid.UUID
    screen_id: uuid.UUID
    detection_id: uuid.UUID | None
    annotation_id: uuid.UUID | None
    monitor_index: int
    bbox: BBox
    localize_path: str
    created_at: datetime


class LocalizeAnnotationCreate(BaseModel):
    screen_id: uuid.UUID
    detection_id: uuid.UUID | None = None
    monitor_index: int = Field(ge=0)
    bbox: BBox | None = None
    action: LocalizeAction

    @model_validator(mode="after")
    def _check_action_combination(self) -> "LocalizeAnnotationCreate":
        # Зеркалит chk_loc_ann_action_combinations из docs/brainscan_schema.sql.
        # С миграции 0007 corrected допускает bbox=NULL (FP-сигнал: «модель нашла
        # регион, врач говорит — ничего нет»).
        if self.action == "confirmed":
            if self.detection_id is None:
                raise ValueError("action='confirmed' requires detection_id")
        elif self.action == "corrected":
            if self.detection_id is None:
                raise ValueError("action='corrected' requires detection_id")
        elif self.action == "created":
            # bbox может быть None: NULL = "области нет" (negative, Mark Null).
            if self.detection_id is not None:
                raise ValueError("action='created' requires detection_id=null")
        return self


class LocalizeAnnotationResponse(BaseModel):
    id: uuid.UUID
    screen_id: uuid.UUID
    detection_id: uuid.UUID | None
    monitor_index: int
    bbox: BBox | None
    # Финальный action ПОСЛЕ server-side normalize (corrected с IoU≥0.95 →
    # confirmed). Клиент может отличаться от того, что прислал.
    action: LocalizeAction
    annotator_id: str
    annotated_at: datetime
    # Weighted-training поля (Phase 10). NULL для confirmed/cold-start.
    correction_type: str | None = None
    iou_with_detection: float | None = None
    training_weight: float = 1.0
