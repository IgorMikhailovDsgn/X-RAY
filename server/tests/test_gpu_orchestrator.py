"""Phase 7b — gpu_orchestrator.reconcile матрица (mock provider, без Selectel)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.gpu import GpuInstance
from app.models.mlops import Dataset
from app.services import gpu_orchestrator
from app.services.system_settings import GPU_AUTOSCALE_KEY, set_bool_setting


@pytest.fixture
def mock_provider(monkeypatch):
    """Подменяет gpu_provider: configured=True, create/delete/status — заглушки
    с записью вызовов."""
    calls = {"create": 0, "delete": [], "status": "ACTIVE"}

    def fake_create(name: str) -> str:
        calls["create"] += 1
        return "srv-fake-1"

    def fake_delete(server_id: str) -> None:
        calls["delete"].append(server_id)

    def fake_status(server_id: str):
        return calls["status"]

    monkeypatch.setattr(gpu_orchestrator.gpu_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gpu_orchestrator.gpu_provider, "create_gpu_server", fake_create)
    monkeypatch.setattr(gpu_orchestrator.gpu_provider, "delete_server", fake_delete)
    monkeypatch.setattr(gpu_orchestrator.gpu_provider, "get_server_status", fake_status)
    return calls


async def _enable_autoscale(sessionmaker) -> None:
    async with sessionmaker() as session:
        await set_bool_setting(session, GPU_AUTOSCALE_KEY, True)
        await session.commit()


async def _seed_dataset(sessionmaker, status: str) -> uuid.UUID:
    async with sessionmaker() as session:
        ds = Dataset(
            model_type="localize",
            version=f"v{uuid.uuid4().hex[:6]}",
            size_total=1,
            size_train=1,
            size_val=0,
            size_test=0,
            manifest_path="s3://x/manifest.json",
            status=status,
        )
        session.add(ds)
        await session.commit()
        await session.refresh(ds)
        return ds.id


async def _insert_instance(sessionmaker, **fields) -> uuid.UUID:
    async with sessionmaker() as session:
        inst = GpuInstance(**fields)
        session.add(inst)
        await session.commit()
        await session.refresh(inst)
        return inst.id


# ----- disabled / no-op -----


async def test_reconcile_disabled_noop(sessionmaker, mock_provider):
    # autoscale выключен (default) → ничего не делаем даже при спросе.
    await _seed_dataset(sessionmaker, "ready")
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "disabled"
    assert mock_provider["create"] == 0


async def test_reconcile_idle_no_instance(sessionmaker, mock_provider):
    await _enable_autoscale(sessionmaker)
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "idle_no_instance"
    assert mock_provider["create"] == 0


# ----- provision -----


async def test_reconcile_provisions_on_demand(sessionmaker, mock_provider):
    await _enable_autoscale(sessionmaker)
    await _seed_dataset(sessionmaker, "ready")
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "provisioned"
    assert result["server_id"] == "srv-fake-1"
    assert mock_provider["create"] == 1
    async with sessionmaker() as session:
        inst = (await session.execute(select(GpuInstance))).scalar_one()
        assert inst.status == "provisioning"
        assert inst.openstack_server_id == "srv-fake-1"


async def test_reconcile_skips_when_not_configured(sessionmaker, monkeypatch):
    await _enable_autoscale(sessionmaker)
    await _seed_dataset(sessionmaker, "ready")
    monkeypatch.setattr(
        gpu_orchestrator.gpu_provider, "is_configured", lambda: False
    )
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "skip_not_configured"


# ----- bump + provisioning→active poll -----


async def test_reconcile_bumps_and_promotes_to_active(sessionmaker, mock_provider):
    await _enable_autoscale(sessionmaker)
    await _seed_dataset(sessionmaker, "training")
    await _insert_instance(
        sessionmaker,
        status="provisioning",
        openstack_server_id="srv-fake-1",
    )
    mock_provider["status"] = "ACTIVE"
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "bump"
    assert result["status"] == "active"
    assert mock_provider["create"] == 0  # уже есть инстанс, не создаём второй


async def test_reconcile_no_second_instance_when_live(sessionmaker, mock_provider):
    await _enable_autoscale(sessionmaker)
    await _seed_dataset(sessionmaker, "ready")
    await _insert_instance(
        sessionmaker, status="active", openstack_server_id="srv-existing"
    )
    async with sessionmaker() as session:
        await gpu_orchestrator.reconcile(session)
    assert mock_provider["create"] == 0


# ----- teardown -----


async def test_reconcile_keeps_warm_when_recently_active(sessionmaker, mock_provider):
    await _enable_autoscale(sessionmaker)
    # demand==0, инстанс активен 5 минут назад → ещё рано гасить (порог 20).
    await _insert_instance(
        sessionmaker,
        status="active",
        openstack_server_id="srv-1",
        last_activity_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "keep_warm"
    assert mock_provider["delete"] == []


async def test_reconcile_tears_down_when_idle(sessionmaker, mock_provider):
    await _enable_autoscale(sessionmaker)
    # demand==0, активность 25 минут назад → idle превышен (20), удаляем.
    await _insert_instance(
        sessionmaker,
        status="active",
        openstack_server_id="srv-1",
        last_activity_at=datetime.now(UTC) - timedelta(minutes=25),
    )
    async with sessionmaker() as session:
        result = await gpu_orchestrator.reconcile(session)
    assert result["action"] == "deleted"
    assert mock_provider["delete"] == ["srv-1"]
    async with sessionmaker() as session:
        inst = (await session.execute(select(GpuInstance))).scalar_one()
        assert inst.status == "deleted"
        assert inst.deleted_at is not None


# ----- force overrides -----


async def test_force_up_and_down(sessionmaker, mock_provider):
    # force_up игнорирует demand и autoscale-флаг.
    async with sessionmaker() as session:
        up = await gpu_orchestrator.force_up(session)
    assert up["action"] == "provisioned"
    assert mock_provider["create"] == 1

    # повторный force_up → already_live
    async with sessionmaker() as session:
        up2 = await gpu_orchestrator.force_up(session)
    assert up2["action"] == "already_live"

    async with sessionmaker() as session:
        down = await gpu_orchestrator.force_down(session)
    assert down["action"] == "deleted"
    assert mock_provider["delete"] == ["srv-fake-1"]

    async with sessionmaker() as session:
        down2 = await gpu_orchestrator.force_down(session)
    assert down2["action"] == "no_live_instance"
