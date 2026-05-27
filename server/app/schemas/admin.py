"""Pydantic-схемы для /api/v1/admin/* endpoint'ов.

Phase 6 — model lifecycle (list/get/promote/archive).
Phase 5 (когда дойдём) — добавит DatasetPreviewResponse, BuildRequest и др.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ModelType = Literal["localize", "tumor"]
ModelStatus = Literal["candidate", "prod", "archived", "failed"]


class AdminModel(BaseModel):
    id: uuid.UUID
    model_type: ModelType
    version: str
    trained_at: datetime
    dataset_id: uuid.UUID | None
    artifact_path: str
    metrics: dict[str, Any]
    status: ModelStatus


class AdminModelList(BaseModel):
    models: list[AdminModel]


class PromoteResponse(BaseModel):
    """Возврат /promote и /archive: что стало с моделью + что вытеснили."""

    promoted: AdminModel | None = None
    archived: AdminModel | None = None
