"""Phase 5b/c — POST /admin/datasets/build pipeline.

Покрытие:
- RBAC (401/403).
- Все ветки статусов: suspended, not_ready, pending_approval (manual),
  gate_failed (auto), queued (auto + gate_passed + dataset built).
- Audit: dataset_builds строки создаются правильно.
- Collision: советуем partial unique index (advisory lock тестируется отдельно).
- Phase 5c: реальное создание dataset row + manifest в S3 + reservation
  annotations + Celery dispatch (мокаем).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models.localize import LocalizeAnnotation
from app.models.mlops import Dataset, DatasetBuild, SystemSetting, TrainingCandidate
from app.models.screenshot import Screenshot


async def _set_mode(sessionmaker, **modes: str) -> None:
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(SystemSetting).where(SystemSetting.key == "training_mode")
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(
                SystemSetting(key="training_mode", value=modes)
            )
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
    sessionmaker,
    *,
    screen_id: uuid.UUID,
    annotator_id: str = "annot-1",
    bbox: dict[str, Any] | None = None,
    action: str = "created",
) -> uuid.UUID:
    async with sessionmaker() as session:
        ann = LocalizeAnnotation(
            screen_id=screen_id,
            monitor_index=0,
            bbox=bbox,
            action=action,
            annotator_id=annotator_id,
        )
        session.add(ann)
        await session.commit()
        await session.refresh(ann)
        return ann.id


# --------------------------- RBAC ---------------------------


async def test_build_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/admin/datasets/build", json={"model_type": "localize"}
    )
    assert resp.status_code == 401


async def test_build_forbids_non_admin(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=auth_headers,
    )
    assert resp.status_code == 403


# --------------------------- mode = suspended ---------------------------


async def test_build_returns_suspended(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _set_mode(sessionmaker, localize="suspended")
    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "suspended"
    assert body["build_id"] is None
    # suspended — no audit row.
    async with sessionmaker() as session:
        builds = (await session.execute(select(DatasetBuild))).scalars().all()
        assert builds == []


# --------------------------- not_ready ---------------------------


async def test_build_returns_not_ready_when_no_annotations(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _set_mode(sessionmaker, localize="manual")
    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["build_id"] is not None
    # Audit row есть, помечена failed с понятным error.
    async with sessionmaker() as session:
        build = (await session.execute(select(DatasetBuild))).scalar_one()
        assert build.status == "failed"
        assert build.error and "not_ready" in build.error
        assert build.finished_at is not None


# --------------------------- mode = manual ---------------------------


async def test_build_manual_creates_pending_candidate(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _set_mode(sessionmaker, localize="manual")
    screen_id = await _seed_screenshot(sessionmaker)
    await _seed_localize_annotation(
        sessionmaker, screen_id=screen_id, bbox={"x": 1, "y": 2, "w": 3, "h": 4}
    )

    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending_approval"
    assert body["candidate_id"] is not None
    assert body["build_id"] is not None
    # Gate провален (1 < min_total=500), но candidate всё равно создан с
    # gate_passed=False — это и есть смысл manual режима.
    assert body["gate_passed"] is False
    assert body["gate_issues"]

    async with sessionmaker() as session:
        candidates = (
            await session.execute(select(TrainingCandidate))
        ).scalars().all()
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.status == "pending"
        assert cand.annotations_count == 1

        build = (await session.execute(select(DatasetBuild))).scalar_one()
        assert build.status == "completed"  # manual считается успехом, candidate в очереди
        assert build.mode == "manual"


# --------------------------- mode = auto + gate_failed ---------------------------


async def test_build_auto_returns_gate_failed_on_low_data(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _set_mode(sessionmaker, localize="auto")
    screen_id = await _seed_screenshot(sessionmaker)
    # Только 1 positive — недостаточно по любому из threshold'ов.
    await _seed_localize_annotation(
        sessionmaker, screen_id=screen_id, bbox={"x": 1, "y": 2, "w": 3, "h": 4}
    )

    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "gate_failed"
    assert body["gate_passed"] is False
    assert body["gate_issues"]
    # Audit row помечена failed с reason.
    async with sessionmaker() as session:
        build = (await session.execute(select(DatasetBuild))).scalar_one()
        assert build.status == "failed"
        assert build.error and build.error.startswith("gate_failed:")
        assert build.mode == "auto"


# --- mode = auto + gate_passed → queued (Phase 5c) ---


async def test_build_auto_gate_passed_creates_dataset(
    client: AsyncClient,
    admin_headers,
    sessionmaker,
    fake_s3,
    monkeypatch,
):
    """End-to-end happy-path Phase 5c: реальная сборка датасета в auto-режиме."""
    # Опускаем пороги до минимума — тестируем pipeline, не gate-логику.
    monkeypatch.setattr(
        "app.services.gates.GATE_THRESHOLDS",
        {
            "localize": {
                "min_total": 2,
                "min_positive": 2,
                "min_negative": 0,
                "min_annotators": 2,
                "max_annotator_pct": 100.0,
            },
            "tumor": {
                "min_total": 2,
                "min_positive": 2,
                "min_negative": 0,
                "min_annotators": 2,
                "max_annotator_pct": 100.0,
            },
        },
    )
    # Перехватываем send_train_task — не хотим публиковать в реальный Redis.
    monkeypatch.setattr(
        "app.services.dataset_pipeline.send_train_task",
        lambda mt, did: "fake-celery-task-id",
    )
    await _set_mode(sessionmaker, localize="auto")

    # Два positive annotations от разных annotator'ов с одного screenshot'а.
    screen_id = await _seed_screenshot(sessionmaker, "mac-1")
    ann_a = await _seed_localize_annotation(
        sessionmaker,
        screen_id=screen_id,
        annotator_id="a",
        bbox={"x": 0, "y": 0, "w": 10, "h": 10},
    )
    ann_b = await _seed_localize_annotation(
        sessionmaker,
        screen_id=screen_id,
        annotator_id="b",
        bbox={"x": 5, "y": 5, "w": 10, "h": 10},
    )

    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["dataset_id"] is not None
    assert body["build_id"] is not None
    assert body["celery_task_id"] == "fake-celery-task-id"
    assert body["gate_passed"] is True

    # 1. Dataset row создан в правильном состоянии.
    async with sessionmaker() as session:
        ds = (await session.execute(select(Dataset))).scalar_one()
        assert ds.status == "ready"
        assert ds.model_type == "localize"
        assert ds.version == "v1"
        assert ds.size_total == 2
        assert ds.size_train + ds.size_val + ds.size_test == 2
        assert ds.manifest_path.startswith("s3://")
        assert ds.stats is not None
        manifest_key = ds.manifest_path.replace(
            f"s3://{ds.manifest_path.split('/')[2]}/", "", 1
        )

    # 2. Manifest загружен в S3 по этому ключу.
    s3_objects = {k: v for (b, k), v in fake_s3.objects.items()}
    assert manifest_key in s3_objects, f"manifest not in S3: keys={list(s3_objects)}"
    manifest = json.loads(s3_objects[manifest_key].decode("utf-8"))
    assert manifest["model_type"] == "localize"
    assert manifest["version"] == "v1"
    assert manifest["dataset_id"] == body["dataset_id"]
    all_samples = (
        manifest["splits"]["train"]
        + manifest["splits"]["val"]
        + manifest["splits"]["test"]
    )
    assert len(all_samples) == 2
    sample_ann_ids = {s["annotation_id"] for s in all_samples}
    assert sample_ann_ids == {str(ann_a), str(ann_b)}
    assert manifest["checksum"].startswith("sha256:")
    assert "seed" in manifest

    # 3. Annotations зарезервированы (dataset_id заполнен).
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(LocalizeAnnotation.id, LocalizeAnnotation.dataset_id)
            )
        ).all()
        assert all(r.dataset_id is not None for r in rows)
        assert {r.dataset_id for r in rows} == {ds.id}

    # 4. Audit row — completed с dataset_id.
    async with sessionmaker() as session:
        build = (await session.execute(select(DatasetBuild))).scalar_one()
        assert build.status == "completed"
        assert build.dataset_id == ds.id
        assert build.error is None


async def test_subsequent_build_increments_version(
    client: AsyncClient,
    admin_headers,
    sessionmaker,
    fake_s3,
    monkeypatch,
):
    """Второй последовательный build даёт v2."""
    monkeypatch.setattr(
        "app.services.gates.GATE_THRESHOLDS",
        {
            "localize": {
                "min_total": 1,
                "min_positive": 1,
                "min_negative": 0,
                "min_annotators": 1,
                "max_annotator_pct": 100.0,
            },
            "tumor": {
                "min_total": 1,
                "min_positive": 1,
                "min_negative": 0,
                "min_annotators": 1,
                "max_annotator_pct": 100.0,
            },
        },
    )
    monkeypatch.setattr(
        "app.services.dataset_pipeline.send_train_task", lambda mt, did: "t1"
    )
    await _set_mode(sessionmaker, localize="auto")

    screen_id = await _seed_screenshot(sessionmaker, "mac-1")
    await _seed_localize_annotation(
        sessionmaker,
        screen_id=screen_id,
        annotator_id="a",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
    )
    r1 = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert r1.json()["status"] == "queued"

    # Залить ещё аннотацию, повторить build — должна получиться v2.
    await _seed_localize_annotation(
        sessionmaker,
        screen_id=screen_id,
        annotator_id="a",
        bbox={"x": 2, "y": 2, "w": 1, "h": 1},
    )
    r2 = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "queued"
    async with sessionmaker() as session:
        versions = sorted(
            (await session.execute(select(Dataset.version))).scalars().all()
        )
        assert versions == ["v1", "v2"]


# --------------------------- collision (parallel build) ---------------------------


async def test_build_collision_via_in_progress_audit_row(
    client: AsyncClient, admin_headers, sessionmaker
):
    """Имитируем уже идущий build вручную inserting in_progress row перед /build.
    Partial unique index `idx_one_active_build` должен отбить второй запуск."""
    await _set_mode(sessionmaker, localize="manual")
    async with sessionmaker() as session:
        session.add(
            DatasetBuild(
                model_type="localize",
                mode="manual",
                triggered_by="manual:test",
                status="in_progress",
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/admin/datasets/build",
        json={"model_type": "localize"},
        headers=admin_headers,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] in ("build_in_progress", "conflict")
