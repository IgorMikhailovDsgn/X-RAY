"""Admin endpoints для GPU auto-orchestration (Phase 7b/10): видимость +
ручной override + master-switch + управление Glance images.

- GET  /admin/gpu/status            — текущий инстанс, demand, флаг автоскейла.
- PUT  /admin/gpu/autoscale         — вкл/выкл gpu_autoscale_enabled.
- POST /admin/gpu/up                — форс-провижн (в обход demand).
- POST /admin/gpu/down              — форс-delete живого инстанса.
- POST /admin/gpu/snapshot          — снапшотит live root-volume в новый
                                      Glance image (durable, переживает delete).
- GET  /admin/gpu/images            — список Glance images проекта.
- DELETE /admin/gpu/images/{id}     — удаление старого snapshot'а.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.api.v1.deps import AdminUser, SessionDep
from app.config import settings
from app.core.exceptions import AppError
from app.models.gpu import GpuInstance
from app.models.mlops import Dataset
from app.schemas.admin import (
    GlanceImageInfo,
    GpuActionResponse,
    GpuAutoscaleUpdate,
    GpuInstanceInfo,
    GpuSnapshotRequest,
    GpuSnapshotResponse,
    GpuStatusResponse,
)
from app.services import gpu_provider
from app.services.gpu_orchestrator import force_down, force_up
from app.services.system_settings import (
    GPU_AUTOSCALE_KEY,
    get_bool_setting,
    set_bool_setting,
)

router = APIRouter()

_LIVE_STATUSES = ("provisioning", "active")


def _to_info(inst: GpuInstance) -> GpuInstanceInfo:
    return GpuInstanceInfo(
        id=inst.id,
        status=inst.status,
        openstack_server_id=inst.openstack_server_id,
        flavor=inst.flavor,
        created_at=inst.created_at,
        ready_at=inst.ready_at,
        last_activity_at=inst.last_activity_at,
        error=inst.error,
    )


@router.get("/status", response_model=GpuStatusResponse)
async def gpu_status(session: SessionDep, _: AdminUser) -> GpuStatusResponse:
    enabled = await get_bool_setting(session, GPU_AUTOSCALE_KEY, False)
    demand = (
        await session.execute(
            select(func.count())
            .select_from(Dataset)
            .where(Dataset.status.in_(("ready", "training")))
        )
    ).scalar_one()
    live = (
        await session.execute(
            select(GpuInstance).where(GpuInstance.status.in_(_LIVE_STATUSES))
        )
    ).scalar_one_or_none()
    return GpuStatusResponse(
        autoscale_enabled=enabled,
        provider_configured=gpu_provider.is_configured(),
        demand=demand,
        idle_teardown_minutes=settings.gpu_idle_teardown_minutes,
        instance=_to_info(live) if live else None,
    )


@router.put("/autoscale", response_model=GpuStatusResponse)
async def set_autoscale(
    payload: GpuAutoscaleUpdate, session: SessionDep, admin: AdminUser
) -> GpuStatusResponse:
    await set_bool_setting(
        session, GPU_AUTOSCALE_KEY, payload.enabled, updated_by=admin.id
    )
    await session.commit()
    return await gpu_status(session, admin)


@router.post("/up", response_model=GpuActionResponse)
async def gpu_up(session: SessionDep, _: AdminUser) -> GpuActionResponse:
    result = await force_up(session)
    return GpuActionResponse(
        action=result.pop("action"),
        instance_id=result.pop("instance_id", None),
        server_id=result.pop("server_id", None),
        status=result.pop("status", None),
        detail=result or None,
    )


@router.post("/down", response_model=GpuActionResponse)
async def gpu_down(session: SessionDep, _: AdminUser) -> GpuActionResponse:
    result = await force_down(session)
    return GpuActionResponse(
        action=result.pop("action"),
        instance_id=result.pop("instance_id", None),
        server_id=result.pop("server_id", None),
        status=result.pop("status", None),
        detail=result or None,
    )


@router.post("/snapshot", response_model=GpuSnapshotResponse)
async def gpu_snapshot(
    payload: GpuSnapshotRequest, session: SessionDep, _: AdminUser,
) -> GpuSnapshotResponse:
    """Снапшотит root-volume живого инстанса в новый Glance image.

    Селектел снимает snapshot фоном (~10-20 мин на 40GB volume) — статус
    image держится `queued`/`saving`, потом `active`. Сам инстанс остаётся
    работать. После того как новый image=`active`, обнови
    `GPU_BOOT_IMAGE_ID` в `deploy/.env` на VPS и перезапусти `server`/`worker`
    — следующий `force_up` поднимет инстанс уже с заранее собранным docker-
    образом внутри (экономит 15+ мин build'а).
    """
    live = (
        await session.execute(
            select(GpuInstance).where(GpuInstance.status.in_(_LIVE_STATUSES))
        )
    ).scalar_one_or_none()
    if live is None or live.openstack_server_id is None:
        raise AppError(
            "no live GPU instance to snapshot",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="no_live_instance",
        )
    image_name = payload.name or (
        f"brainscan-gpu-image-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"
    )
    image_id = await asyncio.to_thread(
        gpu_provider.create_server_image,
        live.openstack_server_id,
        image_name,
    )
    return GpuSnapshotResponse(
        image_id=image_id,
        image_name=image_name,
        server_id=live.openstack_server_id,
    )


@router.get("/images", response_model=list[GlanceImageInfo])
async def list_gpu_images(_: AdminUser) -> list[GlanceImageInfo]:
    images = await asyncio.to_thread(gpu_provider.list_glance_images)
    return [GlanceImageInfo(**img) for img in images]


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gpu_image(image_id: str, _: AdminUser) -> None:
    await asyncio.to_thread(gpu_provider.delete_image, image_id)
