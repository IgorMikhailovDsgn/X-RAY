"""POST /detect — Phase 9 inference pipeline.

Inference (`app.services.inference.predict_all`, `crop_png`) мокаем, чтобы
тесты не тянули torch/ultralytics. Фокус — на endpoint-логике: auth, 404
на screenshot, 503 без deployed моделей, форма ответа, координаты tumor →
screen, поддержка нескольких регионов и tumor per-region.
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
    """Подменяет S3 download_bytes + inference.predict_all/crop_png — без torch.

    Возвращает (calls, set_responses): calls — список вызовов predict_all'а
    как (model_id, image_len); set_responses(seq) — задать последовательность
    возвращаемых list[bbox] для последующих вызовов.
    """
    async def fake_download(self, *, bucket, key):
        return b"fake-png-bytes"
    monkeypatch.setattr(
        "app.storage.s3.S3Client.download_bytes", fake_download
    )
    calls: list[tuple[str, int]] = []
    responses: list[list[dict]] = []

    async def fake_predict_all(model_id, artifact_path, image_bytes):
        calls.append((str(model_id), len(image_bytes)))
        if not responses:
            return []
        return responses.pop(0)

    def fake_crop(image_bytes, bbox):
        return b"fake-crop-png"

    monkeypatch.setattr("app.api.v1.detect.predict_all", fake_predict_all)
    monkeypatch.setattr(detect_module, "crop_png", fake_crop)

    def set_responses(*seq: list[dict]) -> None:
        responses.extend(seq)

    return calls, set_responses


async def test_detect_single_region_with_tumor(
    client: AsyncClient, auth_headers, sessionmaker, mock_inference
):
    calls, set_responses = mock_inference
    # localize → 1 регион; tumor → 1 опухоль в crop-пространстве.
    set_responses(
        [{"x": 10, "y": 20, "w": 100, "h": 80, "confidence": 0.91}],
        [{"x": 5, "y": 6, "w": 30, "h": 40, "confidence": 0.77}],
    )

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
    assert len(body["regions"]) == 1
    region_pred = body["regions"][0]
    assert region_pred["region"] == {"x": 10, "y": 20, "w": 100, "h": 80, "confidence": 0.91}
    # tumor.x/y = region.x/y + local tumor.x/y (15, 26)
    assert region_pred["tumor"] == {"x": 15, "y": 26, "w": 30, "h": 40, "confidence": 0.77}
    # Два вызова: localize, потом tumor (один регион → один crop).
    assert len(calls) == 2


async def test_detect_multiple_regions_each_gets_own_tumor_search(
    client: AsyncClient, auth_headers, sessionmaker, mock_inference
):
    calls, set_responses = mock_inference
    # localize → 2 региона; tumor вызывается по разу на crop каждого региона:
    # для первого находит опухоль, для второго — нет.
    set_responses(
        [
            {"x": 9,    "y": 173, "w": 1447, "h": 1767, "confidence": 0.612},
            {"x": 1448, "y": 162, "w": 1464, "h": 1785, "confidence": 0.608},
        ],
        [{"x": 100, "y": 50, "w": 80, "h": 60, "confidence": 0.85}],
        [],
    )

    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v5")
    await _seed_prod_model(sessionmaker, "tumor", "v6")

    resp = await client.post(
        "/api/v1/detect", headers=auth_headers,
        json={"screenshot_id": str(sid)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["regions"]) == 2

    # Первый регион: с опухолью, координаты сдвинуты на region.x/y.
    first = body["regions"][0]
    assert first["region"]["x"] == 9 and first["region"]["y"] == 173
    assert first["tumor"] == {
        "x": 9 + 100, "y": 173 + 50, "w": 80, "h": 60, "confidence": 0.85,
    }

    # Второй регион: без опухоли.
    second = body["regions"][1]
    assert second["region"]["x"] == 1448 and second["region"]["y"] == 162
    assert second["tumor"] is None

    # 1 localize + 2 tumor вызова.
    assert len(calls) == 3


async def test_detect_no_tumor_model_returns_regions_with_null_tumor(
    client: AsyncClient, auth_headers, sessionmaker, mock_inference
):
    calls, set_responses = mock_inference
    set_responses(
        [{"x": 10, "y": 20, "w": 100, "h": 80, "confidence": 0.91}],
    )

    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v4")
    # tumor НЕ deployed.

    resp = await client.post(
        "/api/v1/detect", headers=auth_headers,
        json={"screenshot_id": str(sid)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["regions"]) == 1
    assert body["regions"][0]["region"]["confidence"] == 0.91
    assert body["regions"][0]["tumor"] is None
    assert body["tumor_model_version"] is None
    # Только localize позвали.
    assert len(calls) == 1


async def test_detect_no_regions_when_localize_finds_nothing(
    client: AsyncClient, auth_headers, sessionmaker, mock_inference
):
    _, set_responses = mock_inference
    set_responses([])  # localize: пусто

    sid = await _seed_screenshot(sessionmaker)
    await _seed_prod_model(sessionmaker, "localize", "v4")
    await _seed_prod_model(sessionmaker, "tumor", "v5")

    resp = await client.post(
        "/api/v1/detect", headers=auth_headers, json={"screenshot_id": str(sid)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["regions"] == []


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
