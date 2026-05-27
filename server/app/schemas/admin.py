"""Pydantic-схемы для /api/v1/admin/* endpoint'ов.

Phase 6 — model lifecycle (list/get/promote/archive).
Phase 5b — datasets/build, datasets/check, datasets/builds, training/mode.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.services.dataset_pipeline import BuildStatus
from app.services.dataset_stats import DatasetStats

ModelType = Literal["localize", "tumor"]
ModelStatus = Literal["candidate", "prod", "archived", "failed"]
TrainingMode = Literal["auto", "manual", "suspended"]


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


# --- Phase 5b: datasets/build, check, mode, builds audit ---


class BuildRequest(BaseModel):
    model_type: ModelType


class BuildResponse(BaseModel):
    status: BuildStatus
    build_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None
    celery_task_id: str | None = None
    stats: DatasetStats | None = None
    gate_passed: bool | None = None
    gate_issues: list[str] | None = None


class CheckResponse(BaseModel):
    model_type: ModelType
    mode: TrainingMode
    stats: DatasetStats
    gate_passed: bool
    gate_issues: list[str]
    ready_to_build: bool  # gate_passed AND mode != 'suspended' AND total_free > 0


class TrainingModeResponse(BaseModel):
    # JSON-объект с режимом для каждой модели.
    localize: TrainingMode
    tumor: TrainingMode


class TrainingModeUpdate(BaseModel):
    # Partial-update: переданные ключи перетирают существующее значение.
    localize: TrainingMode | None = None
    tumor: TrainingMode | None = None


class BuildAuditRow(BaseModel):
    id: uuid.UUID
    model_type: ModelType
    status: Literal["in_progress", "completed", "failed"]
    triggered_by: str
    mode: Literal["auto", "manual"]
    dataset_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class BuildAuditList(BaseModel):
    builds: list[BuildAuditRow]


# --- Phase 5d: training candidates (manual mode queue) ---


CandidateStatus = Literal["pending", "approved", "skipped"]


class CandidateSummary(BaseModel):
    id: uuid.UUID
    model_type: ModelType
    created_at: datetime
    annotations_count: int
    gate_passed: bool
    status: CandidateStatus


class CandidateDetail(CandidateSummary):
    stats: DatasetStats
    gate_issues: list[str] | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    dataset_id: uuid.UUID | None
    skip_reason: str | None


class CandidateList(BaseModel):
    candidates: list[CandidateSummary]


class CandidateSkipRequest(BaseModel):
    reason: str
