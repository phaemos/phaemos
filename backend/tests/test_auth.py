def test_register_success(client):
    res = client.post("/api/v1/auth/register", json={
        "name": "Alice",
        "email": "alice@example.com",
        "password": "Secret123!",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "viewer"  # new users default to least-privilege role
    assert "password_hash" not in body  # hash must never be exposed in responses


def test_register_duplicate_email(client):
    payload = {"name": "Bob", "email": "bob@example.com", "password": "Secret123!"}
    client.post("/api/v1/auth/register", json=payload)
    res = client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 400


def test_login_success(client):
    client.post("/api/v1/auth/register", json={
        "name": "Carol",
        "email": "carol@example.com",
        "password": "Secret123!",
    })
    res = client.post("/api/v1/auth/login", json={
        "email": "carol@example.com",
        "password": "Secret123!",
    })
    assert res.status_code == 200
    body = res.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post("/api/v1/auth/register", json={
        "name": "Dave",
        "email": "dave@example.com",
        "password": "Correct123!",
    })
    res = client.post("/api/v1/auth/login", json={
        "email": "dave@example.com",
        "password": "wrong",
    })
    assert res.status_code == 401


def test_login_unknown_email(client):
    res = client.post("/api/v1/auth/login", json={
        "email": "ghost@example.com",
        "password": "anything",
    })
    assert res.status_code == 401


def test_refresh_token_flow(client):
    client.post("/api/v1/auth/register", json={
        "name": "Eve",
        "email": "eve@example.com",
        "password": "Secret123!",
    })
    login_res = client.post("/api/v1/auth/login", json={
        "email": "eve@example.com",
        "password": "Secret123!",
    })
    assert login_res.status_code == 200
    # The refresh token is delivered as an httpOnly cookie.
    assert "refresh_token" in login_res.cookies

    # Use the cookie to obtain a new access token.
    refresh_res = client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": login_res.cookies["refresh_token"]},
    )
    assert refresh_res.status_code == 200
    body = refresh_res.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_logout_clears_cookie(client):
    client.post("/api/v1/auth/register", json={
        "name": "Frank",
        "email": "frank@example.com",
        "password": "Secret123!",
    })
    client.post("/api/v1/auth/login", json={
        "email": "frank@example.com",
        "password": "Secret123!",
    })
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 204
