"""Phase 8 — /api/v1/internal/training/* lifecycle (start/complete/fail).

GPU-worker дёргает эти endpoint'ы вокруг реальной тренировки. Аутентификация —
X-Internal-Token (как у остальных internal-ручек).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models.localize import LocalizeAnnotation
from app.models.mlops import Dataset, Model
from app.models.screenshot import Screenshot

TOKEN = "test-internal-token-xyz"
HEADERS = {"X-Internal-Token": TOKEN}


@pytest.fixture(autouse=True)
def _configure_internal_token(monkeypatch):
    monkeypatch.setattr(settings, "internal_api_token", TOKEN)


async def _seed_dataset(
    sessionmaker, *, status: str = "ready", reserve_annotation: bool = True
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Создаёт dataset (по умолчанию 'ready') + опционально 1 зарезервированную
    localize-аннотацию. Возвращает (dataset_id, annotation_id)."""
    async with sessionmaker() as session:
        screen = Screenshot(
            captured_at=datetime.now(UTC),
            device_id="mac-1",
            monitor_count=1,
            screen_paths={"0": "s3://x/screen.png"},
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
            manifest_path="s3://bucket/models/datasets/localize/v1/manifest.json",
            status=status,
        )
        session.add(dataset)
        await session.flush()
        ann_id = None
        if reserve_annotation:
            ann = LocalizeAnnotation(
                screen_id=screen.id,
                monitor_index=0,
                bbox={"x": 0, "y": 0, "w": 1, "h": 1},
                action="created",
                annotator_id="a",
                dataset_id=dataset.id,
            )
            session.add(ann)
            await session.flush()
            ann_id = ann.id
        await session.commit()
        return dataset.id, ann_id


# ----- auth gating -----


async def test_training_endpoints_reject_missing_token(client: AsyncClient):
    fake = uuid.uuid4()
    for path, body in [
        (f"/api/v1/internal/training/{fake}/start", None),
        (
            f"/api/v1/internal/training/{fake}/complete",
            {"artifact_path": "s3://x", "metrics": {}},
        ),
        (f"/api/v1/internal/training/{fake}/fail", {"reason": "x"}),
    ]:
        resp = await client.post(path, json=body)
        assert resp.status_code == 401, (path, resp.status_code)


# ----- start -----


async def test_start_marks_ready_dataset_training(client: AsyncClient, sessionmaker):
    dataset_id, _ = await _seed_dataset(sessionmaker, status="ready")
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/start", headers=HEADERS
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_type"] == "localize"
    assert body["version"] == "v1"
    assert body["manifest_path"].endswith("manifest.json")

    async with sessionmaker() as session:
        ds = (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        ).scalar_one()
        assert ds.status == "training"


async def test_start_idempotent_on_training(client: AsyncClient, sessionmaker):
    dataset_id, _ = await _seed_dataset(sessionmaker, status="training")
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/start", headers=HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == "v1"


async def test_start_conflict_on_wrong_status(client: AsyncClient, sessionmaker):
    dataset_id, _ = await _seed_dataset(sessionmaker, status="building")
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/start", headers=HEADERS
    )
    assert resp.status_code == 409, resp.text


async def test_start_404_on_unknown_dataset(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/internal/training/{uuid.uuid4()}/start", headers=HEADERS
    )
    assert resp.status_code == 404


# ----- complete -----


async def test_complete_registers_candidate_and_closes_dataset(
    client: AsyncClient, sessionmaker
):
    dataset_id, _ = await _seed_dataset(sessionmaker, status="training")
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/complete",
        json={
            "artifact_path": "s3://bucket/models/weights/localize/v1/best.pt",
            "metrics": {"map50": 0.8, "recall": 0.7},
            "mlflow_run_id": "run-abc",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "candidate"
    assert body["version"] == "v1"

    async with sessionmaker() as session:
        ds = (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        ).scalar_one()
        assert ds.status == "completed"
        model = (
            await session.execute(select(Model).where(Model.dataset_id == dataset_id))
        ).scalar_one()
        assert model.status == "candidate"
        assert model.model_type == "localize"
        assert model.version == "v1"
        assert model.artifact_path.endswith("best.pt")
        # mlflow_run_id вложен в metrics.
        assert model.metrics["mlflow_run_id"] == "run-abc"
        assert model.metrics["map50"] == 0.8


async def test_complete_idempotent_returns_existing_model(
    client: AsyncClient, sessionmaker
):
    dataset_id, _ = await _seed_dataset(sessionmaker, status="training")
    payload = {
        "artifact_path": "s3://bucket/models/weights/localize/v1/best.pt",
        "metrics": {"map50": 0.5},
    }
    first = await client.post(
        f"/api/v1/internal/training/{dataset_id}/complete",
        json=payload,
        headers=HEADERS,
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/v1/internal/training/{dataset_id}/complete",
        json=payload,
        headers=HEADERS,
    )
    assert second.status_code == 200, second.text
    assert second.json()["model_id"] == first.json()["model_id"]

    async with sessionmaker() as session:
        models = (
            await session.execute(select(Model).where(Model.dataset_id == dataset_id))
        ).scalars().all()
        assert len(models) == 1  # без дубля


async def test_complete_conflict_when_not_training(client: AsyncClient, sessionmaker):
    dataset_id, _ = await _seed_dataset(sessionmaker, status="building")
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/complete",
        json={"artifact_path": "s3://x", "metrics": {}},
        headers=HEADERS,
    )
    assert resp.status_code == 409, resp.text


# ----- fail -----


async def test_fail_rolls_back_dataset_and_frees_annotations(
    client: AsyncClient, sessionmaker
):
    dataset_id, ann_id = await _seed_dataset(sessionmaker, status="training")
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/fail",
        json={"reason": "CUDA OOM"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rolled_back_annotations"] == 1

    async with sessionmaker() as session:
        ds = (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        ).scalar_one()
        assert ds.status == "failed"
        assert ds.failed_reason == "CUDA OOM"
        ann = (
            await session.execute(
                select(LocalizeAnnotation).where(LocalizeAnnotation.id == ann_id)
            )
        ).scalar_one()
        assert ann.dataset_id is None  # вернулась в свободный пул


async def test_fail_idempotent_on_already_failed(client: AsyncClient, sessionmaker):
    dataset_id, _ = await _seed_dataset(
        sessionmaker, status="failed", reserve_annotation=False
    )
    resp = await client.post(
        f"/api/v1/internal/training/{dataset_id}/fail",
        json={"reason": "retry"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rolled_back_annotations"] == 0
