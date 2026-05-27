"""CRUD-обёртки над таблицей system_settings.

Сейчас единственный консумер — training_mode (JSON
`{"localize": "auto|manual|suspended", "tumor": "..."}`). Когда добавим другие
ключи (gate thresholds, cron interval, ...) — допишем сюда же.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mlops import SystemSetting

TrainingMode = Literal["auto", "manual", "suspended"]
TRAINING_MODE_KEY = "training_mode"
_DEFAULT_MODE: dict[str, TrainingMode] = {"localize": "manual", "tumor": "manual"}


async def _get_raw(session: AsyncSession, key: str) -> dict[str, Any] | None:
    row = (
        await session.execute(select(SystemSetting).where(SystemSetting.key == key))
    ).scalar_one_or_none()
    return row.value if row else None


async def get_training_mode(session: AsyncSession) -> dict[str, TrainingMode]:
    raw = await _get_raw(session, TRAINING_MODE_KEY)
    if raw is None:
        # Сидинг должен быть из миграции 0003, но если кто-то снёс строку —
        # тихий fallback на безопасный manual для обеих моделей.
        return dict(_DEFAULT_MODE)
    # Защита от частичной записи: добавляем недостающие ключи дефолтом.
    valid = ("auto", "manual", "suspended")
    return {**_DEFAULT_MODE, **{k: v for k, v in raw.items() if v in valid}}


async def get_mode_for(session: AsyncSession, model_type: str) -> TrainingMode:
    full = await get_training_mode(session)
    return full.get(model_type, "manual")


async def update_training_mode(
    session: AsyncSession,
    updates: dict[str, TrainingMode],
    *,
    updated_by: uuid.UUID,
) -> dict[str, TrainingMode]:
    """Partial-update: переданные ключи пишутся поверх существующего JSON,
    остальные сохраняются. Возвращает результирующий полный mapping.
    """
    current = await get_training_mode(session)
    merged: dict[str, TrainingMode] = {**current, **updates}
    # UPSERT через ORM: если row есть — обновим value+updated_at, нет — создадим.
    existing = (
        await session.execute(
            select(SystemSetting).where(SystemSetting.key == TRAINING_MODE_KEY)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            SystemSetting(
                key=TRAINING_MODE_KEY,
                value=dict(merged),
                updated_by=updated_by,
            )
        )
    else:
        existing.value = dict(merged)
        existing.updated_at = func.now()
        existing.updated_by = updated_by
    await session.flush()
    return merged
