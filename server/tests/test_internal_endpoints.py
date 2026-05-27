"""Phase 5e — /api/v1/internal/* endpoint'ы (cron + maintenance).

Аутентификация через X-Internal-Token. JWT не нужен/не проверяется.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models.localize import LocalizeAnnotation
from app.models.mlops import Dataset, DatasetBuild, SystemSetting
from app.models.screenshot import Screenshot

TOKEN = "test-internal-token-xyz"


@pytest.fixture(autouse=True)
def _configure_internal_token(monkeypatch):
    monkeypatch.setattr(settings, "internal_api_token", TOKEN)


# ----- /datasets/build/cron -----


async def test_cron_build_rejects_missing_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/internal/datasets/build/cron",
        json={"model_type": "localize"},
    )
    assert resp.status_code == 401


async def test_cron_build_rejects_wrong_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/internal/datasets/build/cron",
        json={"model_type": "localize"},
        headers={"X-Internal-Token": "wrong"},
    )
    assert resp.status_code == 401


async def test_cron_build_disabled_when_no_token_configured(
    client: AsyncClient, monkeypatch
):
    # Сбрасываем токен в None — fail-safe: endpoint должен возвращать 401
    # для всех, иначе любой сможет дёрнуть cron на сервере без секретов.
    monkeypatch.setattr(settings, "internal_api_token", None)
    resp = await client.post(
        "/api/v1/internal/datasets/build/cron",
        json={"model_type": "localize"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 401


async def test_cron_build_with_valid_token_returns_suspended(
    client: AsyncClient, sessionmaker
):
    # Переводим режим в suspended — cron должен no-op'нуть со status=suspended.
    async with sessionmaker() as session:
        session.add(
            SystemSetting(
                key="training_mode",
                value={"localize": "suspended", "tumor": "manual"},
            )
        )
        await session.commit()
    resp = await client.post(
        "/api/v1/internal/datasets/build/cron",
        json={"model_type": "localize"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"


async def test_cron_build_triggers_pipeline(
    client: AsyncClient, sessionmaker
):
    # Manual + 0 свободных аннотаций → not_ready, audit-row помечен failed.
    async with sessionmaker() as session:
        session.add(
            SystemSetting(
                key="training_mode",
                value={"localize": "manual", "tumor": "manual"},
            )
        )
        await session.commit()
    resp = await client.post(
        "/api/v1/internal/datasets/build/cron",
        json={"model_type": "localize"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "not_ready"
    # Audit-row triggered_by='cron'.
    async with sessionmaker() as session:
        build = (await session.execute(select(DatasetBuild))).scalar_one()
        assert build.triggered_by == "cron"
        assert build.status == "failed"


# ----- /maintenance/cleanup-hung-builds -----


async def test_cleanup_rejects_missing_token(client: AsyncClient):
    resp = await client.post("/api/v1/internal/maintenance/cleanup-hung-builds")
    assert resp.status_code == 401


async def test_cleanup_noop_when_no_hung_builds(
    client: AsyncClient, sessionmaker
):
    # Свежий in_progress (5 мин назад) — не должен попасть под cleanup (порог 3ч).
    async with sessionmaker() as session:
        session.add(
            DatasetBuild(
                model_type="localize",
                mode="manual",
                triggered_by="manual:test",
                status="in_progress",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()
    resp = await client.post(
        "/api/v1/internal/maintenance/cleanup-hung-builds",
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"cleaned_builds": 0, "rolled_back_datasets": 0}


async def test_cleanup_marks_hung_build_failed(
    client: AsyncClient, sessionmaker
):
    # in_progress 5 часов назад — кандидат на cleanup.
    async with sessionmaker() as session:
        build = DatasetBuild(
            model_type="localize",
            mode="manual",
            triggered_by="manual:test",
            status="in_progress",
            started_at=datetime.now(UTC) - timedelta(hours=5),
        )
        session.add(build)
        await session.commit()
        build_id = build.id

    resp = await client.post(
        "/api/v1/internal/maintenance/cleanup-hung-builds",
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleaned_builds"] == 1
    assert body["rolled_back_datasets"] == 0

    async with sessionmaker() as session:
        fresh = (
            await session.execute(
                select(DatasetBuild).where(DatasetBuild.id == build_id)
            )
        ).scalar_one()
        assert fresh.status == "failed"
        assert fresh.error == "hung_timeout"
        assert fresh.finished_at is not None


async def test_cleanup_rolls_back_dataset_and_annotations(
    client: AsyncClient, sessionmaker
):
    """Hung build с dataset_id → откатываем dataset+annotations."""
    async with sessionmaker() as session:
        # Сидим screenshot + dataset(building) + annotation(reserved за dataset).
        screen = Screenshot(
            captured_at=datetime.now(UTC),
            device_id="mac-1",
            monitor_count=1,
            screen_paths={"0": "s3://x"},
        )
        session.add(screen)
        await session.flush()
        dataset = Dataset(
            model_type="localize",
            version="v1",
            size_total=1,
            size_train=1,
            size_val=0,
            size_test=0,
            manifest_path="s3://x/manifest.json",
            status="building",
        )
        session.add(dataset)
        await session.flush()
        ann = LocalizeAnnotation(
            screen_id=screen.id,
            monitor_index=0,
            bbox={"x": 0, "y": 0, "w": 1, "h": 1},
            action="created",
            annotator_id="a",
            dataset_id=dataset.id,
        )
        session.add(ann)
        session.add(
            DatasetBuild(
                model_type="localize",
                mode="auto",
                triggered_by="cron",
                status="in_progress",
                dataset_id=dataset.id,
                started_at=datetime.now(UTC) - timedelta(hours=5),
            )
        )
        await session.commit()
        dataset_id = dataset.id
        ann_id = ann.id

    resp = await client.post(
        "/api/v1/internal/maintenance/cleanup-hung-builds",
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"cleaned_builds": 1, "rolled_back_datasets": 1}

    async with sessionmaker() as session:
        ds = (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        ).scalar_one()
        assert ds.status == "failed"
        assert ds.failed_reason == "hung_timeout"
        ann_fresh = (
            await session.execute(
                select(LocalizeAnnotation).where(LocalizeAnnotation.id == ann_id)
            )
        ).scalar_one()
        assert ann_fresh.dataset_id is None  # вернулся в свободный пул


async def test_cleanup_preserves_completed_dataset_of_hung_build(
    client: AsyncClient, sessionmaker
):
    """Если dataset уже completed (build реально успел), а audit-row застрял
    как in_progress — НЕ откатываем dataset (это потеряет данные)."""
    async with sessionmaker() as session:
        screen = Screenshot(
            captured_at=datetime.now(UTC),
            device_id="mac-1",
            monitor_count=1,
            screen_paths={"0": "s3://x"},
        )
        session.add(screen)
        await session.flush()
        dataset = Dataset(
            model_type="localize",
            version="v1",
            size_total=0,
            size_train=0,
            size_val=0,
            size_test=0,
            manifest_path="s3://x/manifest.json",
            status="completed",
        )
        session.add(dataset)
        await session.flush()
        session.add(
            DatasetBuild(
                model_type="localize",
                mode="auto",
                triggered_by="cron",
                status="in_progress",
                dataset_id=dataset.id,
                started_at=datetime.now(UTC) - timedelta(hours=5),
            )
        )
        await session.commit()
        dataset_id = dataset.id

    resp = await client.post(
        "/api/v1/internal/maintenance/cleanup-hung-builds",
        headers={"X-Internal-Token": TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleaned_builds"] == 1
    assert body["rolled_back_datasets"] == 0  # completed не трогаем

    async with sessionmaker() as session:
        ds = (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        ).scalar_one()
        assert ds.status == "completed"
        assert ds.failed_reason is None
