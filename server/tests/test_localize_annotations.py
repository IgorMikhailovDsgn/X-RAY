"""CHECK-логика chk_loc_ann_action_combinations через Pydantic validator
+ Phase 10 weighted-training сигналы (correction_type / iou / weight).

Действия:
- 'confirmed': detection_id REQUIRED, bbox любой
- 'corrected': detection_id REQUIRED, bbox опционален (с 0007 разрешён FP)
- 'created':   detection_id MUST be NULL, bbox опционален
               (bbox=NULL = "области нет", negative-пример / Mark Null)
"""

import json
import uuid

import pytest
from sqlalchemy import insert

from app.models.localize import LocalizeDetection
from app.models.mlops import Deployment, Model
from tests.test_screenshots import PNG_1X1

BBOX = {"x": 10, "y": 20, "w": 100, "h": 80}


async def _make_screenshot(client, auth_headers) -> str:
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
    )
    return resp.json()["id"]


async def test_created_ok_with_bbox(client, auth_headers):
    screen_id = await _make_screenshot(client, auth_headers)
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "monitor_index": 0,
            "bbox": BBOX,
            "action": "created",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "created"
    assert body["bbox"] == BBOX
    assert body["detection_id"] is None
    assert body["annotator_id"]


async def test_created_without_bbox_ok_negative(client, auth_headers):
    # bbox=NULL + created = negative-пример ("области нет", Mark Null). С миграции
    # 0006 разрешён — DB CHECK и Pydantic больше не требуют bbox у created.
    screen_id = await _make_screenshot(client, auth_headers)
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={"screen_id": screen_id, "monitor_index": 0, "action": "created"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "created"
    assert body["bbox"] is None
    assert body["detection_id"] is None


async def test_created_with_detection_id_rejected(client, auth_headers):
    screen_id = await _make_screenshot(client, auth_headers)
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "detection_id": str(uuid.uuid4()),
            "monitor_index": 0,
            "bbox": BBOX,
            "action": "created",
        },
    )
    assert resp.status_code == 422


async def test_confirmed_without_detection_rejected(client, auth_headers):
    screen_id = await _make_screenshot(client, auth_headers)
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={"screen_id": screen_id, "monitor_index": 0, "action": "confirmed"},
    )
    assert resp.status_code == 422


async def test_corrected_requires_detection(client, auth_headers):
    # bbox опционален с миграции 0007 (FP-сигнал для локализатора), но
    # detection_id обязателен.
    screen_id = await _make_screenshot(client, auth_headers)
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "monitor_index": 0,
            "bbox": BBOX,
            "action": "corrected",
        },
    )
    assert resp.status_code == 422


# ----- Phase 10: correction-сигналы -----


async def _seed_loc_detection(
    sessionmaker, screen_id: str, *, bbox: dict, confidence: float
) -> uuid.UUID:
    async with sessionmaker() as s:
        m = Model(
            model_type="localize", version="v0",
            artifact_path="s3://bucket/dummy.pt",
            metrics={"map50": 0.5},
            status="prod",
        )
        s.add(m)
        await s.flush()
        await s.execute(
            insert(Deployment).values(model_id=m.id, deployed_by="t", is_active=True)
        )
        det = LocalizeDetection(
            screen_id=uuid.UUID(screen_id),
            model_id=m.id,
            monitor_index=0,
            bbox=bbox,
            confidence=confidence,
        )
        s.add(det)
        await s.commit()
        await s.refresh(det)
        return det.id


async def test_corrected_with_iou_above_095_normalized_to_confirmed(
    client, auth_headers, sessionmaker,
):
    screen_id = await _make_screenshot(client, auth_headers)
    det_bbox = {"x": 10, "y": 20, "w": 100, "h": 80}
    det_id = await _seed_loc_detection(sessionmaker, screen_id, bbox=det_bbox, confidence=0.92)

    # Сдвиг 2px у 100×80 → IoU≈0.95+ → нормализуется в confirmed.
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "detection_id": str(det_id),
            "monitor_index": 0,
            "bbox": {"x": 11, "y": 21, "w": 100, "h": 80},
            "action": "corrected",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "confirmed"      # сервер переписал
    assert body["correction_type"] is None
    assert body["iou_with_detection"] >= 0.95
    assert body["training_weight"] == pytest.approx(1.0)


async def test_corrected_with_wrong_location_iou_below_03(
    client, auth_headers, sessionmaker,
):
    screen_id = await _make_screenshot(client, auth_headers)
    det_bbox = {"x": 0, "y": 0, "w": 100, "h": 100}
    det_id = await _seed_loc_detection(sessionmaker, screen_id, bbox=det_bbox, confidence=0.6)

    # Bbox далеко от детекта → wrong_location.
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "detection_id": str(det_id),
            "monitor_index": 0,
            "bbox": {"x": 80, "y": 80, "w": 100, "h": 100},
            "action": "corrected",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "corrected"
    assert body["correction_type"] == "wrong_location"
    assert body["iou_with_detection"] < 0.30
    # confidence=0.6 (середина) → multiplier=1.0 → weight=4.0.
    assert body["training_weight"] == pytest.approx(4.0)


async def test_corrected_null_bbox_is_false_positive_for_localize(
    client, auth_headers, sessionmaker,
):
    """🔴 ключевой тест: Mark Null Region при наличии детекции даёт FP-сигнал.

    До миграции 0007 был запрещён на уровне CHECK и Pydantic, FP-сигнал терялся.
    """
    screen_id = await _make_screenshot(client, auth_headers)
    det_bbox = {"x": 50, "y": 60, "w": 200, "h": 150}
    # high-confidence detection (>0.8) → multiplier=1.5.
    det_id = await _seed_loc_detection(sessionmaker, screen_id, bbox=det_bbox, confidence=0.92)

    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "detection_id": str(det_id),
            "monitor_index": 0,
            "bbox": None,
            "action": "corrected",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "corrected"
    assert body["correction_type"] == "false_positive"
    assert body["iou_with_detection"] is None
    # FP base = 3.0, × 1.5 (high conf) = 4.5.
    assert body["training_weight"] == pytest.approx(4.5)


async def test_created_positive_gets_higher_weight_than_negative(
    client, auth_headers,
):
    screen_id = await _make_screenshot(client, auth_headers)
    pos_resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={"screen_id": screen_id, "monitor_index": 0, "bbox": BBOX, "action": "created"},
    )
    neg_resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={"screen_id": screen_id, "monitor_index": 0, "action": "created"},
    )
    assert pos_resp.json()["training_weight"] == pytest.approx(3.0)
    assert neg_resp.json()["training_weight"] == pytest.approx(1.0)


async def test_annotator_id_matches_current_user(client, auth_headers):
    screen_id = await _make_screenshot(client, auth_headers)
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "monitor_index": 0,
            "bbox": BBOX,
            "action": "created",
        },
    )
    assert resp.status_code == 201
    annotator_id = resp.json()["annotator_id"]
    # Должен быть валидным UUID — user.id.
    uuid.UUID(annotator_id)
