"""POST /api/v1/detect/annotations — batch endpoint (Phase 10).

Покрытие:
- mixed-touch (regions+tumors с разными action) → независимые INSERT'ы
  в одной транзакции;
- cascade-валидация: tumor под Mark-Null-региона → 422, ничего не пишется;
- reuse существующих localize_images, созданных /detect;
- атомарность: ошибка на N-м item откатывает все ранее flush'нутые строки.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select

from app.models.localize import LocalizeAnnotation, LocalizeDetection, LocalizeImage
from app.models.mlops import Deployment, Model
from app.models.tumor import TumorAnnotation, TumorDetection
from tests.test_screenshots import PNG_1X1


async def _make_screenshot(client, auth_headers) -> str:
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
    )
    return resp.json()["id"]


async def _seed_models(sessionmaker) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as s:
        loc = Model(
            model_type="localize", version="v0",
            artifact_path="s3://bucket/dummy.pt",
            metrics={"map50": 0.5}, status="prod",
        )
        tum = Model(
            model_type="tumor", version="v0",
            artifact_path="s3://bucket/dummy.pt",
            metrics={"map50": 0.5}, status="prod",
        )
        s.add_all([loc, tum])
        await s.flush()
        await s.execute(
            insert(Deployment).values(model_id=loc.id, deployed_by="t", is_active=True)
        )
        await s.execute(
            insert(Deployment).values(model_id=tum.id, deployed_by="t", is_active=True)
        )
        await s.commit()
        return loc.id, tum.id


async def _seed_detected_region(
    sessionmaker,
    screen_id: str,
    *,
    region_bbox: dict,
    region_confidence: float,
    tumor_bbox: dict | None = None,
    tumor_confidence: float | None = None,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Имитирует, что `/detect` уже отработал: создаёт LocalizeDetection +
    LocalizeImage (для будущего tumor FK) + опц. TumorDetection. Возвращает
    (loc_det_id, tum_det_id|None).
    """
    loc_model_id, tum_model_id = await _seed_models(sessionmaker)
    async with sessionmaker() as s:
        loc_det = LocalizeDetection(
            screen_id=uuid.UUID(screen_id), model_id=loc_model_id,
            monitor_index=0, bbox=region_bbox, confidence=region_confidence,
        )
        s.add(loc_det)
        await s.flush()
        loc_img = LocalizeImage(
            screen_id=uuid.UUID(screen_id),
            detection_id=loc_det.id,
            monitor_index=0,
            bbox=region_bbox,
            localize_path="s3://bucket/localize/dummy.png",
        )
        s.add(loc_img)
        await s.flush()
        tum_det_id = None
        if tumor_bbox is not None:
            tum_det = TumorDetection(
                localize_image_id=loc_img.id, model_id=tum_model_id,
                bbox=tumor_bbox, confidence=tumor_confidence or 0.5,
            )
            s.add(tum_det)
            await s.flush()
            tum_det_id = tum_det.id
        await s.commit()
        return loc_det.id, tum_det_id


# ----- auth & validation -----


async def test_batch_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/detect/annotations",
        json={"screen_id": str(uuid.uuid4()), "localize": [], "tumors": []},
    )
    assert resp.status_code == 401


async def test_batch_404_when_screen_missing(client, auth_headers):
    resp = await client.post(
        "/api/v1/detect/annotations",
        headers=auth_headers,
        json={
            "screen_id": str(uuid.uuid4()),
            "localize": [],
            "tumors": [],
        },
    )
    assert resp.status_code == 422
    assert "screen_id" in resp.text


async def test_batch_cascade_rejects_tumor_under_null_region(
    client, auth_headers, sessionmaker,
):
    screen_id = await _make_screenshot(client, auth_headers)
    det_bbox = {"x": 0, "y": 0, "w": 100, "h": 100}
    loc_det_id, tum_det_id = await _seed_detected_region(
        sessionmaker, screen_id,
        region_bbox=det_bbox, region_confidence=0.9,
        tumor_bbox={"x": 10, "y": 10, "w": 20, "h": 20},
        tumor_confidence=0.6,
    )

    resp = await client.post(
        "/api/v1/detect/annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "localize": [
                # Mark Null Region (FP)
                {
                    "detection_id": str(loc_det_id),
                    "monitor_index": 0,
                    "bbox": None,
                    "action": "corrected",
                },
            ],
            "tumors": [
                # ссылается на null-регион → 422, ничего не пишется
                {
                    "region_index": 0,
                    "detection_id": str(tum_det_id),
                    "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
                    "action": "corrected",
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert "Mark-Null" in resp.text or "no crop" in resp.text or "region_index" in resp.text

    # Атомарность: ни одной аннотации.
    async with sessionmaker() as s:
        loc_anns = (await s.execute(select(LocalizeAnnotation))).scalars().all()
        tum_anns = (await s.execute(select(TumorAnnotation))).scalars().all()
        assert len(loc_anns) == 0
        assert len(tum_anns) == 0


# ----- happy paths -----


async def test_batch_mixed_touch_region_confirmed_tumor_corrected(
    client, auth_headers, sessionmaker,
):
    """Главный целевой кейс: модель нашла region+tumor, врач изменил только
    tumor. Region уходит как confirmed (weight=1), tumor — corrected с
    correction_type из IoU и weight>1.
    """
    screen_id = await _make_screenshot(client, auth_headers)
    region_det_bbox = {"x": 50, "y": 60, "w": 200, "h": 150}
    tumor_det_bbox = {"x": 30, "y": 40, "w": 40, "h": 30}  # в crop-space
    loc_det_id, tum_det_id = await _seed_detected_region(
        sessionmaker, screen_id,
        region_bbox=region_det_bbox, region_confidence=0.92,
        tumor_bbox=tumor_det_bbox, tumor_confidence=0.55,
    )

    # Юзер прислал region без изменений (= тот же bbox) и tumor с большим
    # сдвигом (wrong_location).
    resp = await client.post(
        "/api/v1/detect/annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "localize": [
                {
                    "detection_id": str(loc_det_id),
                    "monitor_index": 0,
                    "bbox": region_det_bbox,
                    "action": "corrected",   # клиент шлёт corrected,
                                              # сервер нормализует → confirmed
                },
            ],
            "tumors": [
                {
                    "region_index": 0,
                    "detection_id": str(tum_det_id),
                    "bbox": {"x": 100, "y": 100, "w": 40, "h": 30},  # далеко
                    "action": "corrected",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert len(body["localize"]) == 1
    assert len(body["tumors"]) == 1

    loc = body["localize"][0]
    assert loc["action"] == "confirmed"       # IoU=1.0, нормализовано
    assert loc["correction_type"] is None
    assert loc["training_weight"] == pytest.approx(1.0)

    tum = body["tumors"][0]
    assert tum["action"] == "corrected"
    assert tum["correction_type"] == "wrong_location"
    assert tum["training_weight"] == pytest.approx(4.0)  # WL=4.0, conf=0.55 → ×1.0


async def test_batch_reuses_existing_localize_image_from_detect(
    client, auth_headers, sessionmaker,
):
    """Когда есть detection_id, batch endpoint должен взять существующий
    localize_image (созданный /detect), а не плодить дубликат.
    """
    screen_id = await _make_screenshot(client, auth_headers)
    region_bbox = {"x": 0, "y": 0, "w": 100, "h": 100}
    loc_det_id, _ = await _seed_detected_region(
        sessionmaker, screen_id,
        region_bbox=region_bbox, region_confidence=0.9,
    )

    resp = await client.post(
        "/api/v1/detect/annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "localize": [
                {
                    "detection_id": str(loc_det_id),
                    "monitor_index": 0,
                    "bbox": region_bbox,
                    "action": "confirmed",
                },
            ],
            "tumors": [],
        },
    )
    assert resp.status_code == 201

    # Один существующий localize_image — никакой второй не создан.
    async with sessionmaker() as s:
        loc_imgs = (await s.execute(select(LocalizeImage))).scalars().all()
        assert len(loc_imgs) == 1
        assert loc_imgs[0].detection_id == loc_det_id


async def test_batch_multiple_tumors_independent_actions(
    client, auth_headers, sessionmaker,
):
    """Модель нашла 1 регион + 2 опухоли. Врач: одну confirmed, одну
    corrected. Получаем 2 независимых tumor_annotations.
    """
    screen_id = await _make_screenshot(client, auth_headers)
    region_bbox = {"x": 0, "y": 0, "w": 100, "h": 100}
    loc_det_id, tum_det_id_1 = await _seed_detected_region(
        sessionmaker, screen_id,
        region_bbox=region_bbox, region_confidence=0.95,
        tumor_bbox={"x": 10, "y": 10, "w": 20, "h": 20},
        tumor_confidence=0.85,
    )
    # Вторая опухоль — добавляем ещё одну TumorDetection к тому же localize_image,
    # переиспользуя уже существующую tumor-модель (созданная в _seed_models внутри
    # _seed_detected_region).
    async with sessionmaker() as s:
        tum_model = (
            await s.execute(select(Model).where(Model.model_type == "tumor"))
        ).scalars().first()
        loc_img = (
            await s.execute(select(LocalizeImage).where(LocalizeImage.detection_id == loc_det_id))
        ).scalar_one()
        tum_det_2 = TumorDetection(
            localize_image_id=loc_img.id,
            model_id=tum_model.id,
            bbox={"x": 60, "y": 60, "w": 20, "h": 20},
            confidence=0.3,   # <0.4 → multiplier 0.8
        )
        s.add(tum_det_2)
        await s.commit()
        await s.refresh(tum_det_2)
        tum_det_id_2 = tum_det_2.id

    resp = await client.post(
        "/api/v1/detect/annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "localize": [
                {
                    "detection_id": str(loc_det_id),
                    "monitor_index": 0,
                    "bbox": region_bbox,
                    "action": "confirmed",
                },
            ],
            "tumors": [
                {
                    "region_index": 0,
                    "detection_id": str(tum_det_id_1),
                    "bbox": {"x": 10, "y": 10, "w": 20, "h": 20},  # confirmed
                    "action": "corrected",
                },
                {
                    "region_index": 0,
                    "detection_id": str(tum_det_id_2),
                    "bbox": {"x": 80, "y": 80, "w": 20, "h": 20},  # WL
                    "action": "corrected",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert len(body["tumors"]) == 2
    # Первая: IoU=1 → confirmed.
    assert body["tumors"][0]["action"] == "confirmed"
    assert body["tumors"][0]["training_weight"] == pytest.approx(1.0)
    # Вторая: WL × conf<0.4 → 4.0 × 0.8 = 3.2.
    assert body["tumors"][1]["action"] == "corrected"
    assert body["tumors"][1]["correction_type"] == "wrong_location"
    assert body["tumors"][1]["training_weight"] == pytest.approx(3.2)


async def test_batch_atomic_on_invalid_detection_id(
    client, auth_headers, sessionmaker,
):
    """Ошибка на втором item-е откатывает первый flush."""
    screen_id = await _make_screenshot(client, auth_headers)
    region_bbox = {"x": 0, "y": 0, "w": 100, "h": 100}
    loc_det_id, _ = await _seed_detected_region(
        sessionmaker, screen_id,
        region_bbox=region_bbox, region_confidence=0.9,
    )

    resp = await client.post(
        "/api/v1/detect/annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "localize": [
                {
                    "detection_id": str(loc_det_id),
                    "monitor_index": 0,
                    "bbox": region_bbox,
                    "action": "confirmed",
                },
                {
                    # несуществующий detection_id
                    "detection_id": str(uuid.uuid4()),
                    "monitor_index": 0,
                    "bbox": region_bbox,
                    "action": "confirmed",
                },
            ],
            "tumors": [],
        },
    )
    assert resp.status_code == 422

    # Атомарность: первая аннотация тоже не должна сохраниться.
    async with sessionmaker() as s:
        loc_anns = (await s.execute(select(LocalizeAnnotation))).scalars().all()
        assert len(loc_anns) == 0
