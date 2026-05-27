"""PG advisory lock helpers — защита от параллельного запуска одной операции.

`pg_try_advisory_xact_lock(key int8) → bool` — неблокирующий захват lock'а,
автоматически освобождается на COMMIT или ROLLBACK (xact-scope). Если lock
уже занят другой транзакцией, возвращает FALSE без блокировки.

Используется в Phase 5 для защиты от двух параллельных `POST /datasets/build`
для одного `model_type`. Defence-in-depth дополняется partial unique индексом
`idx_one_active_build` на `dataset_builds`.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _lock_key(scope: str) -> int:
    # PG advisory lock key — int8. Берём первые 4 байта SHA-256 и маскируем
    # до 31 бита, чтобы положить в signed int32-range (некоторые драйверы
    # серьёзно ругаются на int8 outside int32). Коллизии теоретически возможны
    # (1 на ~2 млрд scope-строк), но для нашего use-case (несколько scope'ов)
    # это исчезающе мало.
    digest = hashlib.sha256(scope.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFF_FFFF


async def try_dataset_build_lock(session: AsyncSession, model_type: str) -> bool:
    """Пытается захватить advisory-lock на формирование dataset'а для model_type.
    Возвращает True если захватили, False если уже занят. Lock освобождается
    при COMMIT/ROLLBACK текущей транзакции.
    """
    key = _lock_key(f"dataset_build:{model_type}")
    row = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:k)").bindparams(k=key)
    )
    return bool(row.scalar())
