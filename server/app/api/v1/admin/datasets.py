"""Admin endpoints для управления формированием dataset'ов.

Phase 5b:
- POST /admin/datasets/build  — запустить pipeline (suspended/not_ready/
                                 pending_approval/gate_failed/pending_phase_5c).
- GET  /admin/datasets/check  — dry-run: stats + gate verdict, без побочек.
- GET  /admin/datasets/builds — audit-журнал запусков (обнаружение зависших).

Phase 5c заменит ветку "auto + gate_passed" в pipeline на реальное создание
dataset'а с manifest'ом.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.v1.deps import AdminUser, SessionDep, StorageDep
from app.models.mlops import DatasetBuild
from app.schemas.admin import (
    BuildAuditList,
    BuildAuditRow,
    BuildRequest,
    BuildResponse,
    CheckResponse,
    ModelType,
)
from app.services.dataset_pipeline import run_build
from app.services.dataset_stats import compute_stats
from app.services.gates import evaluate_gates
from app.services.system_settings import get_mode_for

router = APIRouter()


@router.post("/build", response_model=BuildResponse)
async def build_dataset(
    payload: BuildRequest,
    session: SessionDep,
    admin: AdminUser,
    storage: StorageDep,
) -> BuildResponse:
    result = await run_build(
        session,
        storage,
        payload.model_type,
        triggered_by=f"manual:{admin.id}",
    )
    return BuildResponse(**result.model_dump())


@router.get("/check", response_model=CheckResponse)
async def check_dataset(
    session: SessionDep,
    _: AdminUser,
    model_type: ModelType = Query(...),
) -> CheckResponse:
    # Read-only — никаких локов, не пишет в audit. Дашборд-эндпоинт.
    mode = await get_mode_for(session, model_type)
    stats = await compute_stats(session, model_type)
    gate_passed, issues = evaluate_gates(stats, model_type)
    ready = gate_passed and mode != "suspended" and stats.total_free > 0
    return CheckResponse(
        model_type=model_type,
        mode=mode,
        stats=stats,
        gate_passed=gate_passed,
        gate_issues=issues,
        ready_to_build=ready,
    )


@router.get("/builds", response_model=BuildAuditList)
async def list_builds(
    session: SessionDep,
    _: AdminUser,
    model_type: ModelType | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
) -> BuildAuditList:
    stmt = select(DatasetBuild).order_by(DatasetBuild.started_at.desc()).limit(limit)
    if model_type is not None:
        stmt = stmt.where(DatasetBuild.model_type == model_type)
    rows = (await session.execute(stmt)).scalars().all()
    return BuildAuditList(
        builds=[
            BuildAuditRow(
                id=b.id,
                model_type=b.model_type,  # type: ignore[arg-type]
                status=b.status,  # type: ignore[arg-type]
                triggered_by=b.triggered_by,
                mode=b.mode,  # type: ignore[arg-type]
                dataset_id=b.dataset_id,
                started_at=b.started_at,
                finished_at=b.finished_at,
                error=b.error,
            )
            for b in rows
        ]
    )
