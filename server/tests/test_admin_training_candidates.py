"""Phase 5d — /admin/training/candidates list/detail/approve/skip."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select

from app.models.localize import LocalizeAnnotation
from app.models.mlops import (
    Dataset,
    DatasetBuild,
    SystemSetting,
    TrainingCandidate,
)
from app.models.screenshot import Screenshot

# ----- helpers -----


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


async def _seed_localize_annotation(
    sessionmaker, *, screen_id: uuid.UUID, annotator_id: str, bbox: dict
) -> uuid.UUID:
    async with sessionmaker() as session:
        ann = LocalizeAnnotation(
            screen_id=screen_id,
            monitor_index=0,
            bbox=bbox,
            action="created",
            annotator_id=annotator_id,
        )
        session.add(ann)
        await session.commit()
        await session.refresh(ann)
        return ann.id


async def _create_candidate_via_build(
    client: AsyncClient, admin_headers, sessionmaker
) -> str:
    """Запускает /datasets/build в manual-режиме, возвращает candidate_id."""
    await _set_mode(sessionmaker, localize="manual")
    screen_id = await _seed_screenshot(sessionmaker)
    await _seed_localize_annotation(
        sessionmaker, screen_id=screen_id, annotator_id="a", bbox={"x": 1, "y": 1, "w": 1, "h": 1}
    )
    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["candidate_id"]


# ----- RBAC -----


async def test_candidates_endpoints_require_admin(
    client: AsyncClient, auth_headers
):
    fake = uuid.uuid4()
    base = "/api/v1/admin/training/candidates"
    for path, method in [
        (base, "GET"),
        (f"{base}/{fake}", "GET"),
        (f"{base}/{fake}/approve", "POST"),
        (f"{base}/{fake}/skip", "POST"),
    ]:
        if method == "GET":
            r = await client.get(path, headers=auth_headers)
        else:
            r = await client.post(path, json={"reason": "x"}, headers=auth_headers)
        assert r.status_code == 403, (path, r.status_code)


# ----- list / detail -----


async def test_list_empty(client: AsyncClient, admin_headers):
    resp = await client.get("/api/v1/admin/training/candidates", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"candidates": []}


async def test_list_filters_and_detail(
    client: AsyncClient, admin_headers, sessionmaker
):
    candidate_id = await _create_candidate_via_build(client, admin_headers, sessionmaker)

    # Без фильтра — 1.
    resp = await client.get("/api/v1/admin/training/candidates", headers=admin_headers)
    assert resp.status_code == 200
    items = resp.json()["candidates"]
    assert len(items) == 1
    assert items[0]["id"] == candidate_id
    assert items[0]["status"] == "pending"
    assert items[0]["gate_passed"] is False  # 1 annotation < min_total

    # Фильтр по неподходящему статусу — пусто.
    resp = await client.get(
        "/api/v1/admin/training/candidates?status=approved", headers=admin_headers
    )
    assert resp.json() == {"candidates": []}

    # Детальный.
    resp = await client.get(
        f"/api/v1/admin/training/candidates/{candidate_id}", headers=admin_headers
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == candidate_id
    assert detail["model_type"] == "localize"
    assert detail["stats"]["total_free"] == 1
    assert detail["gate_issues"]  # есть list reasons


async def test_detail_not_found(client: AsyncClient, admin_headers):
    resp = await client.get(
        f"/api/v1/admin/training/candidates/{uuid.uuid4()}", headers=admin_headers
    )
    assert resp.status_code == 404


# ----- approve happy path -----


async def test_approve_creates_dataset_and_reserves_annotations(
    client: AsyncClient,
    admin_headers,
    sessionmaker,
    fake_s3,
    monkeypatch,
):
    # Опускаем gate-пороги — нам важно протестировать approve flow, не gate.
    monkeypatch.setattr(
        "app.services.gates.GATE_THRESHOLDS",
        {
            "localize": {
                "min_total": 1, "min_positive": 1, "min_negative": 0,
                "min_annotators": 1, "max_annotator_pct": 100.0,
            },
            "tumor": {
                "min_total": 1, "min_positive": 1, "min_negative": 0,
                "min_annotators": 1, "max_annotator_pct": 100.0,
            },
        },
    )
    monkeypatch.setattr(
        "app.services.dataset_pipeline.send_train_task",
        lambda mt, did: "approve-task-id",
    )
    candidate_id = await _create_candidate_via_build(client, admin_headers, sessionmaker)

    resp = await client.post(
        f"/api/v1/admin/training/candidates/{candidate_id}/approve",
        headers=admin_headers,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["dataset_id"] is not None
    assert body["candidate_id"] == candidate_id
    assert body["celery_task_id"] == "approve-task-id"

    # Candidate перешёл в approved + dataset_id заполнен.
    async with sessionmaker() as session:
        c = (
            await session.execute(
                select(TrainingCandidate).where(
                    TrainingCandidate.id == uuid.UUID(candidate_id)
                )
            )
        ).scalar_one()
        assert c.status == "approved"
        assert c.dataset_id is not None
        assert c.approved_by is not None
        assert c.approved_at is not None

        # Dataset row создан в status='ready'.
        ds = (await session.execute(select(Dataset))).scalar_one()
        assert ds.id == c.dataset_id
        assert ds.status == "ready"

        # Annotation зарезервирована.
        ann_rows = (
            await session.execute(select(LocalizeAnnotation))
        ).scalars().all()
        assert all(a.dataset_id == ds.id for a in ann_rows)

        # Audit-row для approve видна.
        builds = (
            await session.execute(
                select(DatasetBuild).order_by(DatasetBuild.started_at.desc())
            )
        ).scalars().all()
        # Build от initial /datasets/build (manual, completed без dataset_id)
        # и от approve (manual, completed с dataset_id).
        approve_builds = [b for b in builds if b.dataset_id is not None]
        assert len(approve_builds) == 1
        assert approve_builds[0].triggered_by.startswith("approve:")


# ----- approve error paths -----


async def test_approve_not_found(client: AsyncClient, admin_headers):
    resp = await client.post(
        f"/api/v1/admin/training/candidates/{uuid.uuid4()}/approve",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_approve_non_pending_rejected(
    client: AsyncClient, admin_headers, sessionmaker, monkeypatch
):
    monkeypatch.setattr(
        "app.services.gates.GATE_THRESHOLDS",
        {
            "localize": {
                "min_total": 1, "min_positive": 1, "min_negative": 0,
                "min_annotators": 1, "max_annotator_pct": 100.0,
            },
            "tumor": {
                "min_total": 1, "min_positive": 1, "min_negative": 0,
                "min_annotators": 1, "max_annotator_pct": 100.0,
            },
        },
    )
    monkeypatch.setattr(
        "app.services.dataset_pipeline.send_train_task", lambda mt, did: "t"
    )
    candidate_id = await _create_candidate_via_build(client, admin_headers, sessionmaker)

    # Первый approve — успех.
    r1 = await client.post(
        f"/api/v1/admin/training/candidates/{candidate_id}/approve",
        headers=admin_headers,
    )
    assert r1.status_code == 202

    # Повторный approve — 409.
    r2 = await client.post(
        f"/api/v1/admin/training/candidates/{candidate_id}/approve",
        headers=admin_headers,
    )
    assert r2.status_code == 409
    assert r2.json()["error"] == "candidate_state"


# ----- skip -----


async def test_skip_marks_candidate_skipped(
    client: AsyncClient, admin_headers, sessionmaker
):
    candidate_id = await _create_candidate_via_build(client, admin_headers, sessionmaker)

    resp = await client.post(
        f"/api/v1/admin/training/candidates/{candidate_id}/skip",
        json={"reason": "too few positives"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["skip_reason"] == "too few positives"
    assert body["dataset_id"] is None  # ничего не резервировали

    # Аннотации остались свободны.
    async with sessionmaker() as session:
        anns = (await session.execute(select(LocalizeAnnotation))).scalars().all()
        assert all(a.dataset_id is None for a in anns)


async def test_skip_non_pending_rejected(
    client: AsyncClient, admin_headers, sessionmaker
):
    candidate_id = await _create_candidate_via_build(client, admin_headers, sessionmaker)
    await client.post(
        f"/api/v1/admin/training/candidates/{candidate_id}/skip",
        json={"reason": "x"},
        headers=admin_headers,
    )
    # Повтор → 409.
    resp = await client.post(
        f"/api/v1/admin/training/candidates/{candidate_id}/skip",
        json={"reason": "y"},
        headers=admin_headers,
    )
    assert resp.status_code == 409
