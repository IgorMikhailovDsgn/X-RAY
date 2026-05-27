"""Internal endpoints — для cron-тасок воркера. Аутентификация: X-Internal-Token
header (см. `require_internal_token` в deps). JWT не нужен.

Эти endpoint'ы — единственный способ для worker'а вызвать pipeline-логику
server'а: server и worker сидят в разных Docker-image'ах и не делят app/.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import InternalAuth, SessionDep, StorageDep
from app.schemas.admin import BuildRequest, BuildResponse
from app.services.dataset_pipeline import run_build
from app.services.maintenance import CleanupResult, cleanup_hung_builds

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
