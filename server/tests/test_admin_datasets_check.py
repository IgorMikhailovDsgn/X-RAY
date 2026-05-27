"""Phase 5b — GET /admin/datasets/check (dry-run без побочек)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models.localize import LocalizeAnnotation
from app.models.mlops import DatasetBuild, SystemSetting
from app.models.screenshot import Screenshot


async def _set_mode(sessionmaker, **modes: str) -> None:
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(SystemSetting).where(SystemSetting.key == "training_mode")
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(SystemSetting(key="training_mode", value=modes))
        else:
            row.value = {**row.value, **modes}
        await session.commit()


async def _seed_screenshot(sessionmaker, device_id: str = "mac-1") -> uuid.UUID:
    async with sessionmaker() as session:
        s = Screenshot(
            captured_at=datetime.now(UTC),
            device_id=device_id,
            monitor_count=1,
            screen_paths={"0": "s3://screenshots/mac-1/2026-05/x_m0.png"},
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s.id


async def _seed_annotation(
    sessionmaker,
    *,
    screen_id: uuid.UUID,
    annotator_id: str = "a",
    bbox: dict[str, Any] | None = None,
) -> None:
    async with sessionmaker() as session:
        session.add(
            LocalizeAnnotation(
                screen_id=screen_id,
                monitor_index=0,
                bbox=bbox,
                action="created" if bbox else "confirmed",
                annotator_id=annotator_id,
            )
        )
        await session.commit()


async def test_check_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get(
        "/api/v1/admin/datasets/check?model_type=localize", headers=auth_headers
    )
    assert resp.status_code == 403


async def test_check_returns_zero_stats_when_empty(
    client: AsyncClient, admin_headers, sessionmaker
):
    resp = await client.get(
        "/api/v1/admin/datasets/check?model_type=localize", headers=admin_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_type"] == "localize"
    assert body["mode"] == "manual"  # дефолт из миграции 0003
    assert body["stats"]["total_free"] == 0
    assert body["gate_passed"] is False
    assert body["ready_to_build"] is False
    # check — dry-run, audit-row не пишется.
    async with sessionmaker() as session:
        builds = (await session.execute(select(DatasetBuild))).scalars().all()
        assert builds == []


async def test_check_counts_free_annotations(
    client: AsyncClient, admin_headers, sessionmaker
):
    screen_id = await _seed_screenshot(sessionmaker, "mac-1")
    await _seed_annotation(sessionmaker, screen_id=screen_id, bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    await _seed_annotation(sessionmaker, screen_id=screen_id, bbox={"x": 1, "y": 1, "w": 2, "h": 2})

    resp = await client.get(
        "/api/v1/admin/datasets/check?model_type=localize", headers=admin_headers
    )
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["total_free"] == 2
    assert stats["positive"] == 2
    assert stats["negative"] == 0
    assert stats["unique_annotators"] == 1
    assert stats["max_annotator_pct"] == 100.0
    assert stats["by_device"][0]["device_id"] == "mac-1"


async def test_check_ready_to_build_false_when_suspended(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _set_mode(sessionmaker, localize="suspended")
    resp = await client.get(
        "/api/v1/admin/datasets/check?model_type=localize", headers=admin_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "suspended"
    assert body["ready_to_build"] is False
