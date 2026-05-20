import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from app.schemas.common import BBox

TumorAction = Literal["confirmed", "corrected", "created"]


class TumorAnnotationCreate(BaseModel):
    localize_image_id: uuid.UUID
    detection_id: uuid.UUID | None = None
    bbox: BBox | None = None
    action: TumorAction

    @model_validator(mode="after")
    def _check_action_combination(self) -> "TumorAnnotationCreate":
        # Зеркалит chk_tum_ann_action_combinations из docs/brainscan_schema.sql.
        # Особый кейс: 'corrected' допускает bbox=NULL — «модель ошиблась, опухоли нет».
        if self.action == "confirmed":
            if self.detection_id is None:
                raise ValueError("action='confirmed' requires detection_id")
        elif self.action == "corrected":
            if self.detection_id is None:
                raise ValueError("action='corrected' requires detection_id")
        elif self.action == "created":
            if self.detection_id is not None or self.bbox is None:
                raise ValueError(
                    "action='created' requires detection_id=null and bbox"
                )
        return self


class TumorAnnotationResponse(BaseModel):
    id: uuid.UUID
    localize_image_id: uuid.UUID
    detection_id: uuid.UUID | None
    bbox: BBox | None
    action: TumorAction
    annotator_id: str
    annotated_at: datetime
