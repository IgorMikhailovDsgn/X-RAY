"""Phase 5b — GET /admin/datasets/builds (audit-история запусков)."""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient

from app.models.mlops import DatasetBuild


async def _seed_build(sessionmaker, **fields) -> None:
    defaults = dict(
        model_type="localize",
        mode="manual",
        triggered_by="manual:igor",
        status="completed",
        finished_at=datetime.now(UTC),
    )
    defaults.update(fields)
    async with sessionmaker() as session:
        session.add(DatasetBuild(**defaults))
        await session.commit()


async def test_builds_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/admin/datasets/builds", headers=auth_headers)
    assert resp.status_code == 403


async def test_builds_empty(client: AsyncClient, admin_headers):
    resp = await client.get("/api/v1/admin/datasets/builds", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"builds": []}


async def test_builds_lists_and_filters(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _seed_build(sessionmaker, model_type="localize")
    await _seed_build(
        sessionmaker,
        model_type="tumor",
        mode="auto",
        status="failed",
        error="gate_failed: x",
    )
    await _seed_build(
        sessionmaker, model_type="localize", status="failed", error="not_ready"
    )

    resp = await client.get(
        "/api/v1/admin/datasets/builds?model_type=localize", headers=admin_headers
    )
    assert resp.status_code == 200
    items = resp.json()["builds"]
    assert len(items) == 2
    assert all(b["model_type"] == "localize" for b in items)

    resp = await client.get(
        "/api/v1/admin/datasets/builds?limit=1", headers=admin_headers
    )
    assert len(resp.json()["builds"]) == 1
