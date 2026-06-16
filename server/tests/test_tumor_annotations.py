"""CHECK-логика chk_tum_ann_action_combinations + Phase 10 correction-сигналы.

Особый кейс vs localize-annotations: action='corrected' допускает bbox=NULL.
"""

import json
import uuid

import pytest
from sqlalchemy import insert

from app.models.mlops import Deployment, Model
from app.models.tumor import TumorDetection
from tests.test_screenshots import PNG_1X1

BBOX = {"x": 5, "y": 5, "w": 30, "h": 30}


async def _make_localize_image(client, auth_headers) -> str:
    screenshot_meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    s_resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": screenshot_meta},
        files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
    )
    screen_id = s_resp.json()["id"]

    a_resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "monitor_index": 0,
            "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
            "action": "created",
        },
    )
    annotation_id = a_resp.json()["id"]

    image_meta = json.dumps({
        "screen_id": screen_id,
        "annotation_id": annotation_id,
        "monitor_index": 0,
        "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
    })
    img_resp = await client.post(
        "/api/v1/localize-images",
        headers=auth_headers,
        data={"meta": image_meta},
        files={"crop": ("crop.png", PNG_1X1, "image/png")},
    )
    return img_resp.json()["id"]


async def test_created_ok(client, auth_headers):
    image_id = await _make_localize_image(client, auth_headers)
    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={"localize_image_id": image_id, "bbox": BBOX, "action": "created"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["bbox"] == BBOX


async def test_created_without_bbox_ok_negative(client, auth_headers):
    # bbox=NULL + created = negative ("опухоли нет", Mark Null). Разрешён с 0006.
    image_id = await _make_localize_image(client, auth_headers)
    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={"localize_image_id": image_id, "action": "created"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "created"
    assert body["bbox"] is None
    assert body["detection_id"] is None


async def test_confirmed_without_detection_rejected(client, auth_headers):
    image_id = await _make_localize_image(client, auth_headers)
    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={"localize_image_id": image_id, "action": "confirmed"},
    )
    assert resp.status_code == 422


async def test_corrected_allows_null_bbox(client, auth_headers):
    """Особый кейс: модель нашла опухоль, но человек сказал «опухоли нет»."""
    image_id = await _make_localize_image(client, auth_headers)
    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={
            "localize_image_id": image_id,
            "detection_id": str(uuid.uuid4()),
            "bbox": None,
            "action": "corrected",
        },
    )
    # detection_id указывает на несуществующий tumor_detections. С Phase 10 сервер
    # сначала пытается подтянуть детекцию для расчёта correction-сигналов и валит
    # запрос ранее, чем FK сработал бы — ValidationAppError.
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "detection_id" in resp.text


async def test_created_with_detection_rejected(client, auth_headers):
    image_id = await _make_localize_image(client, auth_headers)
    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={
            "localize_image_id": image_id,
            "detection_id": str(uuid.uuid4()),
            "bbox": BBOX,
            "action": "created",
        },
    )
    assert resp.status_code == 422


# ----- Phase 10: correction-сигналы -----


async def _seed_tumor_detection(
    sessionmaker, image_id: str, *, bbox: dict, confidence: float
) -> uuid.UUID:
    async with sessionmaker() as s:
        m = Model(
            model_type="tumor", version="v0",
            artifact_path="s3://bucket/dummy.pt",
            metrics={"map50": 0.5},
            status="prod",
        )
        s.add(m)
        await s.flush()
        await s.execute(
            insert(Deployment).values(model_id=m.id, deployed_by="t", is_active=True)
        )
        det = TumorDetection(
            localize_image_id=uuid.UUID(image_id),
            model_id=m.id,
            bbox=bbox,
            confidence=confidence,
        )
        s.add(det)
        await s.commit()
        await s.refresh(det)
        return det.id


async def test_tumor_corrected_null_bbox_is_false_positive(
    client, auth_headers, sessionmaker,
):
    image_id = await _make_localize_image(client, auth_headers)
    det_bbox = {"x": 10, "y": 10, "w": 50, "h": 40}
    det_id = await _seed_tumor_detection(
        sessionmaker, image_id, bbox=det_bbox, confidence=0.92
    )

    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={
            "localize_image_id": image_id,
            "detection_id": str(det_id),
            "bbox": None,
            "action": "corrected",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "corrected"
    assert body["correction_type"] == "false_positive"
    # FP base 3.0 × 1.5 (high conf) = 4.5.
    assert body["training_weight"] == pytest.approx(4.5)


async def test_tumor_corrected_with_high_iou_normalized_to_confirmed(
    client, auth_headers, sessionmaker,
):
    image_id = await _make_localize_image(client, auth_headers)
    det_bbox = {"x": 10, "y": 10, "w": 50, "h": 40}
    det_id = await _seed_tumor_detection(
        sessionmaker, image_id, bbox=det_bbox, confidence=0.6
    )

    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={
            "localize_image_id": image_id,
            "detection_id": str(det_id),
            "bbox": {"x": 11, "y": 10, "w": 50, "h": 40},  # IoU≈0.98
            "action": "corrected",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "confirmed"
    assert body["correction_type"] is None
    assert body["training_weight"] == pytest.approx(1.0)
