"""Phase 5b — GET/PUT /admin/training/mode."""

from __future__ import annotations

from httpx import AsyncClient


async def test_get_mode_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/admin/training/mode", headers=auth_headers)
    assert resp.status_code == 403


async def test_get_mode_returns_seeded_default(client: AsyncClient, admin_headers):
    resp = await client.get("/api/v1/admin/training/mode", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    # Сид из миграции 0003 — оба manual.
    assert body == {"localize": "manual", "tumor": "manual"}


async def test_put_mode_partial_update(client: AsyncClient, admin_headers):
    resp = await client.put(
        "/api/v1/admin/training/mode",
        headers=admin_headers,
        json={"tumor": "auto"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"localize": "manual", "tumor": "auto"}

    # Повторный GET видит обновление.
    resp = await client.get("/api/v1/admin/training/mode", headers=admin_headers)
    assert resp.json() == {"localize": "manual", "tumor": "auto"}


async def test_put_mode_full_update(client: AsyncClient, admin_headers):
    resp = await client.put(
        "/api/v1/admin/training/mode",
        headers=admin_headers,
        json={"localize": "suspended", "tumor": "auto"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"localize": "suspended", "tumor": "auto"}


async def test_put_mode_rejects_invalid_value(client: AsyncClient, admin_headers):
    resp = await client.put(
        "/api/v1/admin/training/mode",
        headers=admin_headers,
        json={"localize": "garbage"},
    )
    assert resp.status_code == 422
