"""Оркестратор формирования датасета — точка входа `POST /admin/datasets/build`.

Phase 5b/c:
- Получает текущий mode (suspended / manual / auto).
- Захватывает PG advisory lock на (model_type) → 409 при коллизии.
- Создаёт row в `dataset_builds` со статусом `in_progress`. Partial unique
  индекс ловит вторую попытку даже если advisory lock прошёл.
- Считает stats + gate verdict.
- Маршрутизация:
   - `suspended`           → выход {status: 'suspended'} (без записи в audit).
   - `total_free == 0`     → dataset_build.status='failed', return 'not_ready'.
   - `manual`              → создаёт `training_candidate(pending)`, return 'pending_approval'.
   - `auto + gate_failed`  → dataset_build.status='failed', return 'gate_failed'.
   - `auto + gate_passed`  → Phase 5c: формирует датасет (split + manifest в S3 +
                              atomic reservation аннотаций), отправляет train task
                              в Celery, return 'queued'.

Phase 5d допишет approve/skip для candidate'ов; Phase 5e — cron retrain_trigger
по mode + hung-build cleanup.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError
from app.models.mlops import DatasetBuild, TrainingCandidate
from app.services.celery_client import send_train_task
from app.services.dataset_builder import DatasetBuildError, build_and_reserve
from app.services.dataset_stats import DatasetStats, ModelType, compute_stats
from app.services.gates import evaluate_gates
from app.services.locks import try_dataset_build_lock
from app.services.system_settings import get_mode_for
from app.storage import S3Client

logger = logging.getLogger(__name__)

BuildStatus = Literal[
    "suspended",
    "not_ready",
    "pending_approval",
    "gate_failed",
    "queued",
    "failed",
]


class BuildResult(BaseModel):
    status: BuildStatus
    build_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None
    celery_task_id: str | None = None
    stats: DatasetStats | None = None
    gate_passed: bool | None = None
    gate_issues: list[str] | None = None


class BuildCollisionError(ConflictError):
    error_code = "build_in_progress"


class Phase5cBuildError(AppError):
    status_code = 500
    error_code = "build_failed"


async def run_build(
    session: AsyncSession,
    s3: S3Client,
    model_type: ModelType,
    *,
    triggered_by: str,
    mode_override: str | None = None,
) -> BuildResult:
    """Запускает build-pipeline. `triggered_by` — 'cron' или 'manual:{admin_id}'.

    `mode_override` нужен только для cron'а Phase 5e и тестов; обычно
    функция сама читает mode из system_settings.
    """
    mode = mode_override or await get_mode_for(session, model_type)

    if mode == "suspended":
        return BuildResult(status="suspended")

    if mode not in ("auto", "manual"):
        raise AppError(
            f"Invalid training_mode={mode!r} for {model_type}",
            status_code=500,
            error_code="invalid_mode",
        )

    # Advisory lock: моментальная сигнализация о коллизии.
    if not await try_dataset_build_lock(session, model_type):
        raise BuildCollisionError(
            f"Build for {model_type} already in progress",
            details={"model_type": model_type},
        )

    # Audit-row создаём до тяжёлых SELECT'ов — чтобы concurrent caller увидел
    # её через partial unique index ещё до того, как мы успели подсчитать stats.
    build = DatasetBuild(
        model_type=model_type,
        mode=mode,
        triggered_by=triggered_by,
        status="in_progress",
    )
    session.add(build)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise BuildCollisionError(
            f"Build for {model_type} already in progress",
            details={"model_type": model_type},
        ) from exc

    stats = await compute_stats(session, model_type)

    if stats.total_free == 0:
        build.status = "failed"
        build.error = "not_ready: 0 free annotations"
        build.finished_at = func.now()
        await session.commit()
        return BuildResult(
            status="not_ready", build_id=build.id, stats=stats
        )

    gate_passed, gate_issues = evaluate_gates(stats, model_type)

    if mode == "manual":
        candidate = TrainingCandidate(
            model_type=model_type,
            annotations_count=stats.total_free,
            stats=stats.model_dump(),
            gate_passed=gate_passed,
            gate_issues=gate_issues if gate_issues else None,
            status="pending",
        )
        session.add(candidate)
        await session.flush()
        build.status = "completed"
        build.finished_at = func.now()
        await session.commit()
        return BuildResult(
            status="pending_approval",
            build_id=build.id,
            candidate_id=candidate.id,
            stats=stats,
            gate_passed=gate_passed,
            gate_issues=gate_issues,
        )

    # mode == 'auto'
    if not gate_passed:
        build.status = "failed"
        build.error = "gate_failed: " + "; ".join(gate_issues)
        build.finished_at = func.now()
        await session.commit()
        return BuildResult(
            status="gate_failed",
            build_id=build.id,
            stats=stats,
            gate_passed=False,
            gate_issues=gate_issues,
        )

    # auto + gate_passed → реальная сборка датасета (Phase 5c).
    try:
        dataset = await build_and_reserve(session, s3, model_type, stats)
    except DatasetBuildError as exc:
        build.status = "failed"
        build.error = f"build_failed: {exc}"
        build.finished_at = func.now()
        await session.commit()
        return BuildResult(
            status="failed",
            build_id=build.id,
            stats=stats,
            gate_passed=True,
            gate_issues=[str(exc)],
        )

    build.status = "completed"
    build.dataset_id = dataset.id
    build.finished_at = func.now()
    # Atomic commit: dataset(ready) + reserved annotations + audit row.
    # Только после успешного COMMIT'а кидаем задачу в Celery — иначе при
    # rollback'е останется orphan-task в Redis на несуществующий dataset.
    await session.commit()

    try:
        celery_task_id = send_train_task(model_type, dataset.id)
    except Exception:
        # Брокер недоступен — dataset уже зафиксирован как 'ready', можно
        # переотправить вручную. Не падаем, фиксируем в логах.
        logger.exception("Failed to dispatch train task for dataset %s", dataset.id)
        celery_task_id = None

    return BuildResult(
        status="queued",
        build_id=build.id,
        dataset_id=dataset.id,
        celery_task_id=celery_task_id,
        stats=stats,
        gate_passed=True,
        gate_issues=[],
    )
