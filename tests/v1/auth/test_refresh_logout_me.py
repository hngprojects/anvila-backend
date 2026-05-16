import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.user import User

BASE = "/api/v1/auth"


async def _create_verified_user_with_tokens(
    client: AsyncClient,
    db: AsyncSession,
    email: str = "refresh@test.com",
    password: str = "ValidPass1!",
) -> tuple[User, str, str]:
    resp = await client.post(f"{BASE}/register", json={"email": email, "password": password})
    assert resp.status_code == 201

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.email_verified = True
    await db.commit()

    resp = await client.post(f"{BASE}/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    tokens = resp.json()["tokens"]
    return user, tokens["access_token"], tokens["refresh_token"]


# ---------------------------------------------------------------------------
# Refresh tests
# ---------------------------------------------------------------------------


async def test_refresh_valid_token(client: AsyncClient, db_session: AsyncSession):
    _, _, raw_refresh = await _create_verified_user_with_tokens(client, db_session)

    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": raw_refresh})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    parts = data["data"]["access_token"].split(".")
    assert len(parts) == 3, "new access token must be a three-part JWT"


async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": "notavalidtoken"})
    assert resp.status_code == 401


async def test_refresh_expired_token(client: AsyncClient, db_session: AsyncSession):
    _, _, _ = await _create_verified_user_with_tokens(client, db_session, email="expired@test.com")

    result = await db_session.execute(select(User).where(User.email == "expired@test.com"))
    user = result.scalar_one()

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expired_record = RefreshToken(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked=False,
    )
    db_session.add(expired_record)
    await db_session.commit()

    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": raw_token})
    assert resp.status_code == 401


async def test_refresh_revoked_token(client: AsyncClient, db_session: AsyncSession):
    _, _, raw_refresh = await _create_verified_user_with_tokens(
        client, db_session, email="revoked@test.com"
    )

    logout_resp = await client.post(f"{BASE}/logout", json={"refresh_token": raw_refresh})
    assert logout_resp.status_code == 200

    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": raw_refresh})
    assert resp.status_code == 401


async def test_refresh_with_access_token_fails(client: AsyncClient, db_session: AsyncSession):
    _, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="wrongpurpose@test.com"
    )
    # Access token is a JWT — hashing it won't find a RefreshToken row → 401
    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout tests
# ---------------------------------------------------------------------------


async def test_logout_success(client: AsyncClient, db_session: AsyncSession):
    _, _, raw_refresh = await _create_verified_user_with_tokens(
        client, db_session, email="logout_ok@test.com"
    )

    resp = await client.post(f"{BASE}/logout", json={"refresh_token": raw_refresh})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    token_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()
    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record = result.scalar_one()
    await db_session.refresh(record)
    assert record.revoked is True


async def test_logout_idempotent(client: AsyncClient, db_session: AsyncSession):
    _, _, raw_refresh = await _create_verified_user_with_tokens(
        client, db_session, email="logout_idem@test.com"
    )

    r1 = await client.post(f"{BASE}/logout", json={"refresh_token": raw_refresh})
    r2 = await client.post(f"{BASE}/logout", json={"refresh_token": raw_refresh})
    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_logout_invalid_token(client: AsyncClient):
    resp = await client.post(f"{BASE}/logout", json={"refresh_token": "garbage"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /me tests
# ---------------------------------------------------------------------------


async def test_me_success(client: AsyncClient, db_session: AsyncSession):
    _, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="me_ok@test.com"
    )

    resp = await client.get(f"{BASE}/me", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    user_data = data["data"]
    assert "id" in user_data
    assert user_data["email"] == "me_ok@test.com"
    assert "is_admin" in user_data
    assert "email_verified" in user_data
    assert user_data["email_verified"] is True


async def test_me_no_token(client: AsyncClient):
    resp = await client.get(f"{BASE}/me")
    assert resp.status_code == 401


async def test_me_invalid_token(client: AsyncClient):
    resp = await client.get(f"{BASE}/me", headers={"Authorization": "Bearer invalidtoken"})
    assert resp.status_code == 401


async def test_me_with_refresh_token_fails(client: AsyncClient, db_session: AsyncSession):
    _, _, raw_refresh = await _create_verified_user_with_tokens(
        client, db_session, email="me_refresh@test.com"
    )
    # raw_refresh is an opaque string, not a JWT → decode_token raises 401
    resp = await client.get(f"{BASE}/me", headers={"Authorization": f"Bearer {raw_refresh}"})
    assert resp.status_code == 401
