"""Pydantic-схемы для /api/v1/internal/training/* — lifecycle обучения.

GPU-worker (отдельный Docker-image, без app/) вызывает эти endpoint'ы вокруг
реальной тренировки: start (взять dataset в работу), complete (зарегистрировать
обученную модель), fail (откатить dataset + освободить аннотации).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel

ModelType = Literal["localize", "tumor"]


class TrainingStartResponse(BaseModel):
    """Ответ start: всё, что нужно worker'у чтобы скачать манифест и начать."""

    dataset_id: uuid.UUID
    model_type: ModelType
    version: str
    manifest_path: str


class TrainingCompleteRequest(BaseModel):
    artifact_path: str
    metrics: dict[str, Any]
    mlflow_run_id: str | None = None


class TrainingCompleteResponse(BaseModel):
    model_id: uuid.UUID
    version: str
    status: Literal["candidate"]


class TrainingFailRequest(BaseModel):
    reason: str


class TrainingFailResponse(BaseModel):
    dataset_id: uuid.UUID
    rolled_back_annotations: int
