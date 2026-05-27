"""Admin endpoints под training-control:
- режим (auto/manual/suspended) для каждой модели;
- очередь candidate'ов для manual-режима (list/detail/approve/skip).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.v1.deps import AdminUser, SessionDep, StorageDep
from app.models.mlops import TrainingCandidate
from app.schemas.admin import (
    BuildResponse,
    CandidateDetail,
    CandidateList,
    CandidateSkipRequest,
    CandidateStatus,
    CandidateSummary,
    ModelType,
    TrainingModeResponse,
    TrainingModeUpdate,
)
from app.services.dataset_pipeline import (
    CandidateNotFoundError,
    approve_candidate,
    skip_candidate,
)
from app.services.dataset_stats import DatasetStats
from app.services.system_settings import get_training_mode, update_training_mode

router = APIRouter()


# ----------------------------- mode -----------------------------


@router.get("/mode", response_model=TrainingModeResponse)
async def get_mode(session: SessionDep, _: AdminUser) -> TrainingModeResponse:
    mode = await get_training_mode(session)
    return TrainingModeResponse(localize=mode["localize"], tumor=mode["tumor"])


@router.put("/mode", response_model=TrainingModeResponse)
async def put_mode(
    payload: TrainingModeUpdate,
    session: SessionDep,
    admin: AdminUser,
) -> TrainingModeResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    merged = await update_training_mode(session, updates, updated_by=admin.id)
    await session.commit()
    return TrainingModeResponse(localize=merged["localize"], tumor=merged["tumor"])


# ----------------------------- candidates -----------------------------


def _to_summary(c: TrainingCandidate) -> CandidateSummary:
    return CandidateSummary(
        id=c.id,
        model_type=c.model_type,  # type: ignore[arg-type]
        created_at=c.created_at,
        annotations_count=c.annotations_count,
        gate_passed=c.gate_passed,
        status=c.status,  # type: ignore[arg-type]
    )


def _to_detail(c: TrainingCandidate) -> CandidateDetail:
    return CandidateDetail(
        id=c.id,
        model_type=c.model_type,  # type: ignore[arg-type]
        created_at=c.created_at,
        annotations_count=c.annotations_count,
        gate_passed=c.gate_passed,
        status=c.status,  # type: ignore[arg-type]
        stats=DatasetStats.model_validate(c.stats),
        gate_issues=list(c.gate_issues) if c.gate_issues else None,
        approved_by=c.approved_by,
        approved_at=c.approved_at,
        dataset_id=c.dataset_id,
        skip_reason=c.skip_reason,
    )


@router.get("/candidates", response_model=CandidateList)
async def list_candidates(
    session: SessionDep,
    _: AdminUser,
    model_type: ModelType | None = Query(default=None),
    status_filter: CandidateStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> CandidateList:
    stmt = select(TrainingCandidate).order_by(TrainingCandidate.created_at.desc()).limit(limit)
    if model_type is not None:
        stmt = stmt.where(TrainingCandidate.model_type == model_type)
    if status_filter is not None:
        stmt = stmt.where(TrainingCandidate.status == status_filter)
    rows = (await session.execute(stmt)).scalars().all()
    return CandidateList(candidates=[_to_summary(c) for c in rows])


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
async def get_candidate(
    candidate_id: uuid.UUID,
    session: SessionDep,
    _: AdminUser,
) -> CandidateDetail:
    c = await session.get(TrainingCandidate, candidate_id)
    if c is None:
        raise CandidateNotFoundError(f"Candidate {candidate_id} not found")
    return _to_detail(c)


@router.post(
    "/candidates/{candidate_id}/approve",
    response_model=BuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_candidate_endpoint(
    candidate_id: uuid.UUID,
    session: SessionDep,
    admin: AdminUser,
    storage: StorageDep,
) -> BuildResponse:
    result = await approve_candidate(session, storage, candidate_id, admin.id)
    return BuildResponse(**result.model_dump())


@router.post(
    "/candidates/{candidate_id}/skip", response_model=CandidateDetail
)
async def skip_candidate_endpoint(
    candidate_id: uuid.UUID,
    payload: CandidateSkipRequest,
    session: SessionDep,
    admin: AdminUser,
) -> CandidateDetail:
    c = await skip_candidate(session, candidate_id, payload.reason, admin.id)
    return _to_detail(c)
