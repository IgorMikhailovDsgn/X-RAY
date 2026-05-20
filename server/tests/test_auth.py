async def test_register_returns_token_pair(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "doc@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


async def test_register_duplicate_email_409(client):
    payload = {"email": "doc@example.com", "password": "password123"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["error"] == "conflict"


async def test_register_short_password_422(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "doc@example.com", "password": "short"},
    )
    assert resp.status_code == 422


async def test_login_success(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "doc@example.com", "password": "password123"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "doc@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password_401(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "doc@example.com", "password": "password123"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "doc@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_refresh_with_access_token_rejected(client):
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "doc@example.com", "password": "password123"},
    )
    access = reg.json()["access_token"]
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": access}
    )
    assert resp.status_code == 401


async def test_refresh_returns_new_pair(client):
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "doc@example.com", "password": "password123"},
    )
    refresh = reg.json()["refresh_token"]
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
