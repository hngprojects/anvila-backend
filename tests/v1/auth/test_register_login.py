import pytest
from httpx import AsyncClient

BASE = "/api/v1/auth"


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


async def test_register_success(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/register",
        json={"email": "alice@example.com", "password": "strongpass1"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert data["email_verified"] is False
    assert data["is_active"] is True
    assert "id" in data


async def test_register_with_display_name(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/register",
        json={
            "email": "bob@example.com",
            "password": "strongpass1",
            "display_name": "Bob",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["display_name"] == "Bob"


async def test_register_duplicate_email(client: AsyncClient):
    payload = {"email": "dup@example.com", "password": "strongpass1"}
    r1 = await client.post(f"{BASE}/register", json=payload)
    assert r1.status_code == 201
    r2 = await client.post(f"{BASE}/register", json=payload)
    assert r2.status_code == 409


async def test_register_short_password(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/register",
        json={"email": "short@example.com", "password": "short"},
    )
    assert resp.status_code == 422


async def test_register_invalid_email(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/register",
        json={"email": "not-an-email", "password": "strongpass1"},
    )
    assert resp.status_code == 422


async def test_register_missing_fields(client: AsyncClient):
    resp = await client.post(f"{BASE}/register", json={"email": "x@example.com"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


async def test_login_success(client: AsyncClient):
    await client.post(
        f"{BASE}/register",
        json={"email": "login@example.com", "password": "strongpass1"},
    )
    resp = await client.post(
        f"{BASE}/login",
        json={"email": "login@example.com", "password": "strongpass1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tokens" in data
    assert data["tokens"]["token_type"] == "bearer"
    assert data["tokens"]["access_token"]
    assert data["tokens"]["refresh_token"]
    assert data["user"]["email"] == "login@example.com"


async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        f"{BASE}/register",
        json={"email": "wrongpw@example.com", "password": "strongpass1"},
    )
    resp = await client.post(
        f"{BASE}/login",
        json={"email": "wrongpw@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/login",
        json={"email": "ghost@example.com", "password": "doesntmatter"},
    )
    assert resp.status_code == 401


async def test_login_missing_password(client: AsyncClient):
    resp = await client.post(f"{BASE}/login", json={"email": "x@example.com"})
    assert resp.status_code == 422


async def test_login_returns_user_fields(client: AsyncClient):
    await client.post(
        f"{BASE}/register",
        json={"email": "fields@example.com", "password": "strongpass1", "display_name": "Tester"},
    )
    resp = await client.post(
        f"{BASE}/login",
        json={"email": "fields@example.com", "password": "strongpass1"},
    )
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["display_name"] == "Tester"
    assert "id" in user
    assert "created_at" in user


async def test_login_access_token_is_jwt(client: AsyncClient):
    await client.post(
        f"{BASE}/register",
        json={"email": "jwt@example.com", "password": "strongpass1"},
    )
    resp = await client.post(
        f"{BASE}/login",
        json={"email": "jwt@example.com", "password": "strongpass1"},
    )
    token = resp.json()["tokens"]["access_token"]
    parts = token.split(".")
    assert len(parts) == 3, "Access token should be a three-part JWT"
