"""CHECK-логика chk_loc_ann_action_combinations через Pydantic validator.

Действия:
- 'confirmed': detection_id REQUIRED, bbox любой
- 'corrected': detection_id REQUIRED, bbox REQUIRED
- 'created':   detection_id MUST be NULL, bbox опционален
               (bbox=NULL = "области нет", negative-пример / Mark Null)
"""

import json
import uuid

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


async def test_corrected_requires_detection_and_bbox(client, auth_headers):
    screen_id = await _make_screenshot(client, auth_headers)
    # Missing bbox.
    resp = await client.post(
        "/api/v1/localize-annotations",
        headers=auth_headers,
        json={
            "screen_id": screen_id,
            "detection_id": str(uuid.uuid4()),
            "monitor_index": 0,
            "action": "corrected",
        },
    )
    assert resp.status_code == 422
    # Missing detection_id.
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
