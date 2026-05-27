"""Phase 5e — cleanup зависших dataset_builds.

Зависший build = `status='in_progress'` дольше N часов. Это симптом одного из
сценариев:
- Server-процесс упал/перезапустился во время `run_build` после INSERT'а
  dataset_builds row, но до COMMIT'а.
- Долгий S3-upload manifest'а (≥ N часов) — практически невозможно, но защита.
- Deadlock на advisory lock — теоретический.

Лечение:
1. Помечаем build как `failed` с error='hung_timeout'.
2. Если build успел создать dataset (build.dataset_id заполнен) — откатываем:
   - UPDATE annotations SET dataset_id=NULL WHERE dataset_id=X (возврат в пул);
   - UPDATE datasets SET status='failed', failed_reason='hung_timeout'.

Запускается раз в час через Celery beat (Phase 5e добавляет в schedule).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.localize import LocalizeAnnotation
from app.models.mlops import Dataset, DatasetBuild
from app.models.tumor import TumorAnnotation


class CleanupResult(BaseModel):
    cleaned_builds: int
    rolled_back_datasets: int


async def cleanup_hung_builds(
    session: AsyncSession, *, max_age_hours: int = 3
) -> CleanupResult:
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    hung = (
        await session.execute(
            select(DatasetBuild).where(
                DatasetBuild.status == "in_progress",
                DatasetBuild.started_at < cutoff,
            )
        )
    ).scalars().all()
    if not hung:
        return CleanupResult(cleaned_builds=0, rolled_back_datasets=0)

    rolled_back = 0
    finished_at = datetime.now(UTC)
    for build in hung:
        build.status = "failed"
        build.error = "hung_timeout"
        build.finished_at = finished_at

        if build.dataset_id is None:
            continue

        # Build успел создать dataset — откатываем reservation.
        dataset = await session.get(Dataset, build.dataset_id)
        if dataset is None or dataset.status in ("completed", "failed"):
            # Уже завершён успешно или ранее откатан — не трогаем.
            continue
        dataset.status = "failed"
        dataset.failed_reason = "hung_timeout"
        ann_model = (
            LocalizeAnnotation if build.model_type == "localize" else TumorAnnotation
        )
        await session.execute(
            update(ann_model)
            .where(ann_model.dataset_id == dataset.id)
            .values(dataset_id=None)
        )
        rolled_back += 1

    await session.commit()
    return CleanupResult(
        cleaned_builds=len(hung), rolled_back_datasets=rolled_back
    )
