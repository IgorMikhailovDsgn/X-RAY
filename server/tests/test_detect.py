"""POST /detect — Phase 9 inference pipeline.

Inference (`app.services.inference.predict`, `crop_png`) мокаем, чтобы тесты
не тянули torch/ultralytics. Фокус — на endpoint-логике: auth, 404 на
screenshot, 503 без deployed моделей, форма ответа, координаты tumor → screen.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import insert

from app.api.v1 import detect as detect_module
from app.models.mlops import Deployment, Model
from app.models.screenshot import Screenshot


async def _seed_screenshot(
    sessionmaker, screen_url: str = "s3://bucket/screenshots/x_m0.png"
) -> uuid.UUID:
    async with sessionmaker() as session:
        s = Screenshot(
            captured_at=datetime.now(UTC),
            device_id="mac-1",
            monitor_count=1,
            screen_paths={"0": screen_url},
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s.id


async def _seed_prod_model(
    sessionmaker, model_type: str, version: str = "v1",
    artifact_path: str | None = None,
) -> uuid.UUID:
    async with sessionmaker() as session:
        m = Model(
            model_type=model_type, version=version,
            artifact_path=artifact_path or f"s3://bucket/models/{model_type}/{version}/weights/best.pt",
            metrics={"map50": 0.9},
            status="prod",
        )
        session.add(m)
        await session.flush()
        await session.execute(
            insert(Deployment).values(
                model_id=m.id, deployed_by="manual:test", is_active=True,
            )
        )
        await session.commit()
        return m.id


# ----- auth & basic errors -----


async def test_detect_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/detect", json={"screenshot_id": str(uuid.uuid4())})
    assert resp.status_code == 401


async def test_detect_404_when_screenshot_missing(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v1/detect",
        headers=auth_headers,
        json={"screenshot_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "not_found"


async def test_detect_503_when_no_localize_model(
    client: AsyncClient, auth_headers, sessionmaker
):
    sid = await _seed_screenshot(sessionmaker)
    resp = await client.post(
        "/api/v1/detect", headers=auth_headers, json={"screenshot_id": str(sid)},
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"] == "no_model_deployed"


# ----- happy paths (inference mocked) -----


@pytest.fixture
def mock_inference(monkeypatch, fake_s3):
    """Подменяем S3 download_bytes + inference.predict/crop_png — без torch."""
    async def fake_download(self, *, bucket, key):
        return b"fake-png-bytes"
    monkeypatch.setattr(
        "app.storage.s3.S3Client.download_bytes", fake_download
    )
    calls: list[tuple[str, int]] = []

    async def fake_predict(model_id, artifact_path, image_bytes):
        calls.append((str(model_id), len(image_bytes)))
        # Первый вызов (localize) → region; второй (tumor) → tumor-в-crop'е.
        return {"x": 10, "y": 20, "w": 100, "h": 80, "confidence": 0.91} if len(calls) == 1 \
            else {"x": 5, "y": 6, "w": 30, "h": 40, "confidence": 0.77}

    def fake_crop(image_bytes, bbox):
        return b"fake-crop-png"

    monkeypatch.setattr("app.api.v1.detect.predict", fake_predict)
    monkeypatch.setattr(detect_module, "crop_png", fake_crop)
    return calls


async def test_detect_returns_region_and_tumor_in_screen_coords(
    client: AsyncClient, auth_headers, sessionmaker, mock_inference
):
    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v4")
    await _seed_prod_model(sessionmaker, "tumor", "v5")

    resp = await client.post(
        "/api/v1/detect", headers=auth_headers,
        json={"screenshot_id": str(sid), "monitor_index": 0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["screenshot_id"] == str(sid)
    assert body["monitor_index"] == 0
    assert body["localize_model_version"] == "v4"
    assert body["tumor_model_version"] == "v5"
    assert body["region"] == {"x": 10, "y": 20, "w": 100, "h": 80, "confidence": 0.91}
    # tumor.x/y = region.x/y + local tumor.x/y (15, 26)
    assert body["tumor"] == {"x": 15, "y": 26, "w": 30, "h": 40, "confidence": 0.77}
    # Два вызова predict: localize, потом tumor (на crop'е).
    assert len(mock_inference) == 2


async def test_detect_returns_only_region_when_no_tumor_model(
    client: AsyncClient, auth_headers, sessionmaker, mock_inference
):
    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v4")
    # tumor НЕ deployed.
    resp = await client.post(
        "/api/v1/detect", headers=auth_headers,
        json={"screenshot_id": str(sid)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["region"] is not None
    assert body["tumor"] is None
    assert body["tumor_model_version"] is None
    # Только localize позвали.
    assert len(mock_inference) == 1


async def test_detect_returns_404_when_monitor_not_in_screen_paths(
    client: AsyncClient, auth_headers, sessionmaker
):
    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v4")
    resp = await client.post(
        "/api/v1/detect", headers=auth_headers,
        json={"screenshot_id": str(sid), "monitor_index": 5},
    )
    assert resp.status_code == 404, resp.text


async def test_detect_returns_null_region_when_localize_finds_nothing(
    client: AsyncClient, auth_headers, sessionmaker, monkeypatch, fake_s3
):
    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v4")
    await _seed_prod_model(sessionmaker, "tumor", "v5")

    async def fake_download(self, *, bucket, key):
        return b"fake-png"
    monkeypatch.setattr("app.storage.s3.S3Client.download_bytes", fake_download)

    async def fake_predict(*a, **kw):
        return None
    monkeypatch.setattr("app.api.v1.detect.predict", fake_predict)

    resp = await client.post(
        "/api/v1/detect", headers=auth_headers, json={"screenshot_id": str(sid)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["region"] is None
    assert body["tumor"] is None
