"""Phase 7b — /admin/gpu/* (status, autoscale toggle, force up/down) + RBAC."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.gpu import GpuInstance
from app.services import gpu_orchestrator


@pytest.fixture
def mock_provider(monkeypatch):
    calls = {"create": 0, "delete": []}
    monkeypatch.setattr(gpu_orchestrator.gpu_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        gpu_orchestrator.gpu_provider,
        "create_gpu_server",
        lambda name: calls.__setitem__("create", calls["create"] + 1) or "srv-1",
    )
    monkeypatch.setattr(
        gpu_orchestrator.gpu_provider,
        "delete_server",
        lambda sid: calls["delete"].append(sid),
    )
    monkeypatch.setattr(
        gpu_orchestrator.gpu_provider, "get_server_status", lambda sid: "ACTIVE"
    )
    return calls


# ----- RBAC -----


async def test_gpu_endpoints_require_admin(client: AsyncClient, auth_headers):
    base = "/api/v1/admin/gpu"
    r = await client.get(f"{base}/status", headers=auth_headers)
    assert r.status_code == 403
    r = await client.put(
        f"{base}/autoscale", json={"enabled": True}, headers=auth_headers
    )
    assert r.status_code == 403
    for path in (f"{base}/up", f"{base}/down"):
        r = await client.post(path, headers=auth_headers)
        assert r.status_code == 403


# ----- status + autoscale toggle -----


async def test_status_default_disabled(client: AsyncClient, admin_headers):
    resp = await client.get("/api/v1/admin/gpu/status", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["autoscale_enabled"] is False
    assert body["demand"] == 0
    assert body["instance"] is None
    assert body["idle_teardown_minutes"] == 20


async def test_autoscale_toggle(client: AsyncClient, admin_headers):
    resp = await client.put(
        "/api/v1/admin/gpu/autoscale", json={"enabled": True}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["autoscale_enabled"] is True
    # повторный GET видит включённым
    resp = await client.get("/api/v1/admin/gpu/status", headers=admin_headers)
    assert resp.json()["autoscale_enabled"] is True


# ----- force up / down -----


async def test_force_up_then_down(
    client: AsyncClient, admin_headers, sessionmaker, mock_provider
):
    up = await client.post("/api/v1/admin/gpu/up", headers=admin_headers)
    assert up.status_code == 200, up.text
    assert up.json()["action"] == "provisioned"
    assert mock_provider["create"] == 1
    async with sessionmaker() as session:
        inst = (await session.execute(select(GpuInstance))).scalar_one()
        assert inst.status == "provisioning"

    # status теперь показывает инстанс
    st = await client.get("/api/v1/admin/gpu/status", headers=admin_headers)
    assert st.json()["instance"]["status"] == "provisioning"

    down = await client.post("/api/v1/admin/gpu/down", headers=admin_headers)
    assert down.status_code == 200
    assert down.json()["action"] == "deleted"
    assert mock_provider["delete"] == ["srv-1"]


async def test_force_down_no_instance(client: AsyncClient, admin_headers):
    resp = await client.post("/api/v1/admin/gpu/down", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["action"] == "no_live_instance"
