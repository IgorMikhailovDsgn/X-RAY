import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DeployedModel(BaseModel):
    id: uuid.UUID
    model_type: Literal["localize", "tumor"]
    version: str
    deployed_at: datetime


class DeployedModelList(BaseModel):
    models: list[DeployedModel]
