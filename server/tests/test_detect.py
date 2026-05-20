import uuid


async def test_detect_requires_auth(client):
    resp = await client.post(
        "/api/v1/detect", json={"screenshot_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 401


async def test_detect_returns_503_stub(client, auth_headers):
    resp = await client.post(
        "/api/v1/detect",
        headers=auth_headers,
        json={"screenshot_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "no_model_deployed"
    assert "message" in body
