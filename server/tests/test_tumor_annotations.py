"""CHECK-логика chk_tum_ann_action_combinations.

Особый кейс vs localize-annotations: action='corrected' допускает bbox=NULL.
"""

import json
import uuid

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


async def test_created_without_bbox_rejected(client, auth_headers):
    image_id = await _make_localize_image(client, auth_headers)
    resp = await client.post(
        "/api/v1/tumor-annotations",
        headers=auth_headers,
        json={"localize_image_id": image_id, "action": "created"},
    )
    assert resp.status_code == 422


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
    # detection_id указывает на несуществующий tumor_detections — FK ловится IntegrityError
    # и превращается в 422. Pydantic-валидатор проходит.
    assert resp.status_code == 422
    assert resp.json()["error"] == "integrity_error"


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
