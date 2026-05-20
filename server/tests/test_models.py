async def test_models_deployed_requires_auth(client):
    resp = await client.get("/api/v1/models/deployed")
    assert resp.status_code == 401


async def test_models_deployed_empty(client, auth_headers):
    resp = await client.get("/api/v1/models/deployed", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"models": []}
