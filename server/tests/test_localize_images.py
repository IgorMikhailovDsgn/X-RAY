import json
import re

from tests.test_screenshots import PNG_1X1

# Layout: <device_id>/<DD.MM.YY>/<image_id>.png
LOCALIZE_KEY_RE = re.compile(
    r"^[A-Za-z0-9_-]+/\d{2}\.\d{2}\.\d{2}/[0-9a-f-]{36}\.png$"
)


async def _create_screenshot_and_annotation(client, auth_headers) -> tuple[str, str]:
    """Создаёт скриншот + annotation типа 'created' (для FK на localize_images)."""
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    s_resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
    )
    assert s_resp.status_code == 201
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
    assert a_resp.status_code == 201, a_resp.text
    return screen_id, a_resp.json()["id"]


async def test_localize_image_requires_source(client, auth_headers):
    screen_id, _ = await _create_screenshot_and_annotation(client, auth_headers)
    meta = json.dumps({
        "screen_id": screen_id,
        "monitor_index": 0,
        "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
    })
    resp = await client.post(
        "/api/v1/localize-images",
        headers=auth_headers,
        data={"meta": meta},
        files={"crop": ("crop.png", PNG_1X1, "image/png")},
    )
    assert resp.status_code == 422


async def test_localize_image_with_annotation(client, auth_headers, fake_s3):
    screen_id, annotation_id = await _create_screenshot_and_annotation(client, auth_headers)
    meta = json.dumps({
        "screen_id": screen_id,
        "annotation_id": annotation_id,
        "monitor_index": 0,
        "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
    })
    resp = await client.post(
        "/api/v1/localize-images",
        headers=auth_headers,
        data={"meta": meta},
        files={"crop": ("crop.png", PNG_1X1, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["screen_id"] == screen_id
    assert body["annotation_id"] == annotation_id
    assert body["bbox"] == {"x": 10, "y": 20, "w": 100, "h": 80}
    assert body["localize_path"].startswith("s3://localize/")
    assert len(fake_s3.objects) == 2  # 1 screenshot + 1 crop
    # Layout: crop key = mac-1/<DD.MM.YY>/<image_id>.png
    localize_keys = [k for b, k in fake_s3.objects if b == "localize"]
    assert len(localize_keys) == 1
    key = localize_keys[0]
    assert key.startswith("mac-1/"), f"localize key not under device folder: {key}"
    assert LOCALIZE_KEY_RE.match(key), f"key not in new layout: {key}"


async def test_localize_image_wrong_content_type_rejected(client, auth_headers):
    screen_id, annotation_id = await _create_screenshot_and_annotation(client, auth_headers)
    meta = json.dumps({
        "screen_id": screen_id,
        "annotation_id": annotation_id,
        "monitor_index": 0,
        "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
    })
    resp = await client.post(
        "/api/v1/localize-images",
        headers=auth_headers,
        data={"meta": meta},
        files={"crop": ("crop.jpg", PNG_1X1, "image/jpeg")},
    )
    assert resp.status_code == 422
