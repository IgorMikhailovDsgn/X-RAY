"""Internal endpoints — для cron-тасок воркера. Аутентификация: X-Internal-Token
header (см. `require_internal_token` в deps). JWT не нужен.

Эти endpoint'ы — единственный способ для worker'а вызвать pipeline-логику
server'а: server и worker сидят в разных Docker-image'ах и не делят app/.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.v1.deps import InternalAuth, SessionDep, StorageDep
from app.schemas.admin import BuildRequest, BuildResponse
from app.schemas.training import (
    TrainingCompleteRequest,
    TrainingCompleteResponse,
    TrainingFailRequest,
    TrainingFailResponse,
    TrainingStartResponse,
)
from app.services.dataset_pipeline import run_build
from app.services.gpu_orchestrator import reconcile as gpu_reconcile
from app.services.maintenance import CleanupResult, cleanup_hung_builds
from app.services.training_lifecycle import (
    complete_training,
    fail_training,
    start_training,
)

router = APIRouter()


@router.post("/datasets/build/cron", response_model=BuildResponse)
async def cron_trigger_build(
    payload: BuildRequest,
    session: SessionDep,
    storage: StorageDep,
    _: InternalAuth,
) -> BuildResponse:
    """Вызывается из `retrain_trigger.check_and_trigger` (Celery beat 3:00 UTC).
    Идемпотентно: если mode=suspended или коллизия — вернёт соответствующий
    статус без побочек.
    """
    result = await run_build(
        session,
        storage,
        payload.model_type,
        triggered_by="cron",
    )
    return BuildResponse(**result.model_dump())


@router.post("/maintenance/cleanup-hung-builds", response_model=CleanupResult)
async def cron_cleanup_hung_builds(
    session: SessionDep,
    _: InternalAuth,
) -> CleanupResult:
    """Вызывается ежечасной cleanup-таской воркера. Помечает зависшие
    in_progress dataset_builds как failed и откатывает зарезервированные
    аннотации обратно в свободный пул.
    """
    return await cleanup_hung_builds(session)


@router.post("/gpu/reconcile")
async def cron_gpu_reconcile(
    session: SessionDep,
    _: InternalAuth,
) -> dict[str, Any]:
    """Вызывается gpu-autoscaler beat-таской (~каждые 2 мин). Поднимает/держит/
    гасит GPU-инстанс по спросу (datasets в ready|training). No-op если
    gpu_autoscale_enabled=false."""
    return await gpu_reconcile(session)


# --------------------------- training lifecycle (Phase 8) ---------------------------


@router.post("/training/{dataset_id}/start", response_model=TrainingStartResponse)
async def training_start(
    dataset_id: uuid.UUID,
    session: SessionDep,
    _: InternalAuth,
) -> TrainingStartResponse:
    """GPU-worker берёт dataset в работу: 'ready' → 'training'. Возвращает
    manifest_path, чтобы worker скачал манифест и crop'ы из S3."""
    return await start_training(session, dataset_id)


@router.post(
    "/training/{dataset_id}/complete", response_model=TrainingCompleteResponse
)
async def training_complete(
    dataset_id: uuid.UUID,
    payload: TrainingCompleteRequest,
    session: SessionDep,
    _: InternalAuth,
) -> TrainingCompleteResponse:
    """Регистрирует обученную модель (status='candidate') и закрывает dataset
    ('completed'). Promote в prod — отдельным admin-действием."""
    return await complete_training(
        session,
        dataset_id,
        artifact_path=payload.artifact_path,
        metrics=payload.metrics,
        mlflow_run_id=payload.mlflow_run_id,
    )


@router.post("/training/{dataset_id}/fail", response_model=TrainingFailResponse)
async def training_fail(
    dataset_id: uuid.UUID,
    payload: TrainingFailRequest,
    session: SessionDep,
    _: InternalAuth,
) -> TrainingFailResponse:
    """Откат при провале обучения: dataset → 'failed', зарезервированные
    аннотации возвращаются в свободный пул (dataset_id=NULL)."""
    return await fail_training(session, dataset_id, payload.reason)
