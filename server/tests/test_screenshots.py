import json
import re

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xcf"
    b"\xc0\xc0\xc0\xc0\x00\x00\x00\x07\x00\x01\x02\xa5\x9f\xfe\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)

# Layout (после Phase 4): <device_id>/<YYYY-MM>/<screenshot_id>_m<N>.png
SCREENSHOT_KEY_RE = re.compile(
    r"^[A-Za-z0-9_-]+/\d{4}-\d{2}/[0-9a-f-]{36}_m\d+\.png$"
)


async def test_screenshots_requires_auth(client):
    resp = await client.post("/api/v1/screenshots")
    assert resp.status_code == 401


async def test_screenshots_single_monitor(client, auth_headers, fake_s3):
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["monitor_count"] == 1
    assert set(body["screen_paths"].keys()) == {"0"}
    assert body["screen_paths"]["0"].startswith("s3://screenshots/")
    # Phase 4 layout: ключ внутри бакета = mac-1/YYYY-MM/<uuid>_m0.png
    (_bucket, key) = next(iter(fake_s3.objects))
    assert key.startswith("mac-1/")
    assert key.endswith("_m0.png")
    assert SCREENSHOT_KEY_RE.match(key), f"key not in new layout: {key}"
    assert len(fake_s3.objects) == 1


async def test_screenshots_two_monitors(client, auth_headers, fake_s3):
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 2})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={
            "screen_0": ("m0.png", PNG_1X1, "image/png"),
            "screen_1": ("m1.png", PNG_1X1, "image/png"),
        },
    )
    assert resp.status_code == 201
    assert set(resp.json()["screen_paths"].keys()) == {"0", "1"}
    assert len(fake_s3.objects) == 2
    # Оба монитора должны лежать в одной партиции <device_id>/<YYYY-MM>/.
    prefixes = {k.rsplit("/", 1)[0] for _, k in fake_s3.objects}
    assert len(prefixes) == 1, f"monitors split across partitions: {prefixes}"


async def test_screenshots_rejects_bad_device_id(client, auth_headers):
    # `/`, `..`, пробелы и спецсимволы запрещены — не дать вылезти из префикса в S3.
    for bad in ["mac/1", "../etc", "mac 1", "mac\x00"]:
        meta = json.dumps({"device_id": bad, "monitor_count": 1})
        resp = await client.post(
            "/api/v1/screenshots",
            headers=auth_headers,
            data={"meta": meta},
            files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
        )
        assert resp.status_code == 422, f"device_id={bad!r} should be rejected"


async def test_screenshots_missing_screen_0_rejected(client, auth_headers):
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_1": ("m1.png", PNG_1X1, "image/png")},
    )
    assert resp.status_code == 422


async def test_screenshots_monitor_count_mismatch_rejected(client, auth_headers):
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 2})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_0": ("m0.png", PNG_1X1, "image/png")},
    )
    assert resp.status_code == 422


async def test_screenshots_wrong_content_type_rejected(client, auth_headers):
    meta = json.dumps({"device_id": "mac-1", "monitor_count": 1})
    resp = await client.post(
        "/api/v1/screenshots",
        headers=auth_headers,
        data={"meta": meta},
        files={"screen_0": ("m0.jpg", PNG_1X1, "image/jpeg")},
    )
    assert resp.status_code == 422
