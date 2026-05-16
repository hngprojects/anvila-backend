import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

BASE = "/api/v1/auth"


async def _register(client: AsyncClient, email: str) -> dict:
    resp = await client.post(
        f"{BASE}/register",
        json={"email": email, "password": "strongpass1"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _get_user(db: AsyncSession, email: str) -> User:
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one()


# ---------------------------------------------------------------------------
# verify-email tests
# ---------------------------------------------------------------------------


async def test_verify_email_success(client: AsyncClient, db_session: AsyncSession):
    await _register(client, "verify_ok@example.com")
    user = await _get_user(db_session, "verify_ok@example.com")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    user.verification_token_hash = token_hash
    user.verification_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(f"{BASE}/verify-email", json={"token": raw_token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email_verified"] is True
    assert data["email"] == "verify_ok@example.com"


async def test_verify_email_clears_token_fields(client: AsyncClient, db_session: AsyncSession):
    await _register(client, "verify_clear@example.com")
    user = await _get_user(db_session, "verify_clear@example.com")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    user.verification_token_hash = token_hash
    user.verification_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db_session.flush()
    await db_session.commit()

    await client.post(f"{BASE}/verify-email", json={"token": raw_token})

    await db_session.refresh(user)
    assert user.verification_token_hash is None
    assert user.verification_token_expires_at is None


async def test_verify_email_invalid_token(client: AsyncClient):
    resp = await client.post(f"{BASE}/verify-email", json={"token": "totally-made-up-token"})
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


async def test_verify_email_already_verified(client: AsyncClient, db_session: AsyncSession):
    await _register(client, "already_verified@example.com")
    user = await _get_user(db_session, "already_verified@example.com")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    user.verification_token_hash = token_hash
    user.verification_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    user.email_verified = True
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(f"{BASE}/verify-email", json={"token": raw_token})
    assert resp.status_code == 400
    assert "already verified" in resp.json()["detail"]


async def test_verify_email_expired_token(client: AsyncClient, db_session: AsyncSession):
    await _register(client, "expired_token@example.com")
    user = await _get_user(db_session, "expired_token@example.com")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    user.verification_token_hash = token_hash
    user.verification_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(f"{BASE}/verify-email", json={"token": raw_token})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"]


async def test_verify_email_missing_token(client: AsyncClient):
    resp = await client.post(f"{BASE}/verify-email", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# resend-verification tests
# ---------------------------------------------------------------------------


async def test_resend_verification_success(client: AsyncClient, db_session: AsyncSession):
    await _register(client, "resend_ok@example.com")

    resp = await client.post(
        f"{BASE}/resend-verification", json={"email": "resend_ok@example.com"}
    )
    assert resp.status_code == 204

    user = await _get_user(db_session, "resend_ok@example.com")
    await db_session.refresh(user)
    assert user.verification_token_hash is not None
    assert user.verification_token_expires_at is not None


async def test_resend_verification_unknown_email_returns_204(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/resend-verification", json={"email": "ghost_resend@example.com"}
    )
    assert resp.status_code == 204


async def test_resend_verification_already_verified_returns_400(
    client: AsyncClient, db_session: AsyncSession
):
    await _register(client, "resend_verified@example.com")
    user = await _get_user(db_session, "resend_verified@example.com")
    user.email_verified = True
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"{BASE}/resend-verification", json={"email": "resend_verified@example.com"}
    )
    assert resp.status_code == 400
    assert "already verified" in resp.json()["detail"]


async def test_resend_verification_refreshes_token(client: AsyncClient, db_session: AsyncSession):
    await _register(client, "resend_refresh@example.com")
    user = await _get_user(db_session, "resend_refresh@example.com")
    original_hash = user.verification_token_hash

    await client.post(
        f"{BASE}/resend-verification", json={"email": "resend_refresh@example.com"}
    )

    await db_session.refresh(user)
    assert user.verification_token_hash != original_hash


async def test_resend_verification_invalid_email_format(client: AsyncClient):
    resp = await client.post(f"{BASE}/resend-verification", json={"email": "not-an-email"})
    assert resp.status_code == 422
