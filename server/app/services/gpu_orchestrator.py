"""GPU auto-orchestration reconcile-логика (Phase 7b).

Единая точка принятия решений «поднять / держать / погасить» GPU-инстанс.
Дёргается каждые ~2 мин beat-таской воркера через /internal/gpu/reconcile, а
также force_up/force_down из admin-endpoint'ов.

demand = кол-во datasets в статусе ready|training. Это durable-сигнал спроса:
`build_and_reserve` ставит ready ДО enqueue train-таски, train флипает в
training, по завершении → completed/failed. Пока demand>0 — инстанс нужен и не
гасится (в т.ч. на многочасовом обучении). idle-teardown считается от
last_activity_at (последний момент demand>0).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.gpu import GpuInstance
from app.models.mlops import Dataset
from app.services import gpu_provider
from app.services.system_settings import GPU_AUTOSCALE_KEY, get_bool_setting

logger = logging.getLogger(__name__)

_SERVER_NAME = "brainscan-gpu-worker"
_DEMAND_STATUSES = ("ready", "training")
_LIVE_STATUSES = ("provisioning", "active")


async def _count_demand(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Dataset)
            .where(Dataset.status.in_(_DEMAND_STATUSES))
        )
    ).scalar_one()


async def _get_live_instance(session: AsyncSession) -> GpuInstance | None:
    # Partial unique idx_one_live_gpu гарантирует ≤1 живой строки.
    return (
        await session.execute(
            select(GpuInstance).where(GpuInstance.status.in_(_LIVE_STATUSES))
        )
    ).scalar_one_or_none()


async def _provision(session: AsyncSession) -> dict[str, Any]:
    if not gpu_provider.is_configured():
        return {"action": "skip_not_configured"}
    try:
        server_id = gpu_provider.create_gpu_server(name=_SERVER_NAME)
    except Exception as exc:
        logger.exception("GPU provision failed")
        session.add(
            GpuInstance(
                status="failed",
                flavor=settings.gpu_flavor_id,
                error=str(exc)[:500],
            )
        )
        await session.commit()
        return {"action": "provision_failed", "error": str(exc)}

    inst = GpuInstance(
        status="provisioning",
        openstack_server_id=server_id,
        flavor=settings.gpu_flavor_id,
    )
    session.add(inst)
    try:
        await session.commit()
    except IntegrityError:
        # Гонка: другой reconcile/force_up уже создал живой инстанс. Откатываем
        # и пытаемся прибрать только что созданный сервер, чтобы не платить.
        await session.rollback()
        logger.warning("Live GPU instance already exists; deleting just-created server")
        try:
            gpu_provider.delete_server(server_id)
        except Exception:
            logger.exception("Failed to clean up duplicate server %s", server_id)
        return {"action": "provision_raced"}
    await session.refresh(inst)
    return {
        "action": "provisioned",
        "instance_id": str(inst.id),
        "server_id": server_id,
    }


async def _teardown(session: AsyncSession, inst: GpuInstance) -> dict[str, Any]:
    inst.status = "deleting"
    await session.commit()
    if inst.openstack_server_id:
        try:
            gpu_provider.delete_server(inst.openstack_server_id)
        except Exception as exc:
            logger.exception("GPU delete failed")
            inst.error = str(exc)[:500]
    inst.status = "deleted"
    inst.deleted_at = func.now()
    await session.commit()
    return {"action": "deleted", "instance_id": str(inst.id)}


async def _refresh_provisioning_status(
    session: AsyncSession, inst: GpuInstance
) -> None:
    """Поллит Nova-статус provisioning-инстанса, переводит в active/failed."""
    if inst.status != "provisioning" or not inst.openstack_server_id:
        return
    try:
        nova_status = gpu_provider.get_server_status(inst.openstack_server_id)
    except Exception as exc:
        logger.warning("Nova status poll failed: %s", exc)
        return
    if nova_status == "ACTIVE":
        inst.status = "active"
        inst.ready_at = func.now()
    elif nova_status in ("ERROR", None):
        inst.status = "failed"
        inst.error = f"nova status={nova_status}"


async def reconcile(session: AsyncSession) -> dict[str, Any]:
    if not await get_bool_setting(session, GPU_AUTOSCALE_KEY, False):
        return {"action": "disabled"}

    demand = await _count_demand(session)
    live = await _get_live_instance(session)

    if demand > 0:
        if live is None:
            return await _provision(session)
        live.last_activity_at = func.now()
        await _refresh_provisioning_status(session, live)
        await session.commit()
        await session.refresh(live)
        return {
            "action": "bump",
            "instance_id": str(live.id),
            "status": live.status,
            "demand": demand,
        }

    # demand == 0
    if live is None:
        return {"action": "idle_no_instance"}

    idle_for = datetime.now(UTC) - live.last_activity_at
    if idle_for > timedelta(minutes=settings.gpu_idle_teardown_minutes):
        return await _teardown(session, live)
    return {
        "action": "keep_warm",
        "instance_id": str(live.id),
        "idle_seconds": int(idle_for.total_seconds()),
    }


# --- admin force overrides (в обход demand/enabled) ---


async def force_up(session: AsyncSession) -> dict[str, Any]:
    live = await _get_live_instance(session)
    if live is not None:
        return {"action": "already_live", "instance_id": str(live.id),
                "status": live.status}
    return await _provision(session)


async def force_down(session: AsyncSession) -> dict[str, Any]:
    live = await _get_live_instance(session)
    if live is None:
        return {"action": "no_live_instance"}
    return await _teardown(session, live)
