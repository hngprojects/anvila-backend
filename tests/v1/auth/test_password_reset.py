import hashlib
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserProvider
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User

BASE = "/api/v1/auth"


async def _register_and_verify(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    password: str = "ValidPass1!",
) -> User:
    await client.post(f"{BASE}/register", json={"email": email, "password": password})
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.email_verified = True
    await db.commit()
    return user


async def _create_reset_token(
    db: AsyncSession,
    user_id,
    minutes_until_expiry: int = 60,
) -> tuple[str, PasswordResetToken]:
    raw = "test-reset-token-exactly-32-chars-x"
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes_until_expiry)
    record = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(record)
    await db.commit()
    return raw, record


# ---------------------------------------------------------------------------
# Forgot password tests
# ---------------------------------------------------------------------------


async def test_forgot_password_existing_email(client: AsyncClient, db_session: AsyncSession):
    user = await _register_and_verify(client, db_session, "forgot_ok@test.com")

    resp = await client.post(f"{BASE}/forgot-password", json={"email": user.email})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    assert result.scalar_one_or_none() is not None


async def test_forgot_password_nonexistent_email(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(f"{BASE}/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200

    result = await db_session.execute(select(PasswordResetToken))
    assert result.scalar_one_or_none() is None


async def test_forgot_password_oauth_user(client: AsyncClient, db_session: AsyncSession):
    oauth_user = User(
        email="oauth_reset@test.com",
        provider=UserProvider.GOOGLE,
        email_verified=True,
    )
    db_session.add(oauth_user)
    await db_session.commit()
    await db_session.refresh(oauth_user)

    resp = await client.post(f"{BASE}/forgot-password", json={"email": "oauth_reset@test.com"})
    assert resp.status_code == 200

    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == oauth_user.id)
    )
    assert result.scalar_one_or_none() is None


async def test_forgot_password_always_200(client: AsyncClient):
    emails = [
        "a@nowhere.com",
        "b@nowhere.com",
        "c@nowhere.com",
        "d@nowhere.com",
        "e@nowhere.com",
    ]
    for email in emails:
        resp = await client.post(f"{BASE}/forgot-password", json={"email": email})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Reset password tests
# ---------------------------------------------------------------------------


async def test_reset_password_valid_token(client: AsyncClient, db_session: AsyncSession):
    user = await _register_and_verify(
        client, db_session, "reset_ok@test.com", password="OldPass99!"
    )
    raw, record = await _create_reset_token(db_session, user.id)

    resp = await client.post(
        f"{BASE}/reset-password",
        json={"token": raw, "new_password": "NewPass99!"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    await db_session.refresh(record)
    assert record.used_at is not None

    bad_login = await client.post(
        f"{BASE}/login", json={"email": user.email, "password": "OldPass99!"}
    )
    assert bad_login.status_code == 401

    good_login = await client.post(
        f"{BASE}/login", json={"email": user.email, "password": "NewPass99!"}
    )
    assert good_login.status_code == 200


async def test_reset_password_used_token(client: AsyncClient, db_session: AsyncSession):
    user = await _register_and_verify(client, db_session, "used_token@test.com")
    raw, _ = await _create_reset_token(db_session, user.id)

    r1 = await client.post(
        f"{BASE}/reset-password",
        json={"token": raw, "new_password": "NewPass99!"},
    )
    assert r1.status_code == 200

    r2 = await client.post(
        f"{BASE}/reset-password",
        json={"token": raw, "new_password": "AnotherPass99!"},
    )
    assert r2.status_code == 400


async def test_reset_password_expired_token(client: AsyncClient, db_session: AsyncSession):
    user = await _register_and_verify(client, db_session, "expired_reset@test.com")
    raw, _ = await _create_reset_token(db_session, user.id, minutes_until_expiry=-10)

    resp = await client.post(
        f"{BASE}/reset-password",
        json={"token": raw, "new_password": "NewPass99!"},
    )
    assert resp.status_code == 400


async def test_reset_password_invalid_token(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/reset-password",
        json={"token": "randomgarbage", "new_password": "NewPass99!"},
    )
    assert resp.status_code == 400


async def test_reset_password_weak_password(client: AsyncClient, db_session: AsyncSession):
    user = await _register_and_verify(client, db_session, "weak_pw@test.com")
    raw, _ = await _create_reset_token(db_session, user.id)

    resp = await client.post(
        f"{BASE}/reset-password",
        json={"token": raw, "new_password": "weak"},
    )
    assert resp.status_code == 422


async def test_reset_password_revokes_sessions(client: AsyncClient, db_session: AsyncSession):
    user = await _register_and_verify(client, db_session, "revoke_session@test.com")

    login_resp = await client.post(
        f"{BASE}/login",
        json={"email": user.email, "password": "ValidPass1!"},
    )
    raw_refresh = login_resp.json()["tokens"]["refresh_token"]

    raw_reset, _ = await _create_reset_token(db_session, user.id)
    await client.post(
        f"{BASE}/reset-password",
        json={"token": raw_reset, "new_password": "NewPass99!"},
    )

    refresh_resp = await client.post(f"{BASE}/refresh", json={"refresh_token": raw_refresh})
    assert refresh_resp.status_code == 401


async def test_reset_password_no_password_hash(client: AsyncClient, db_session: AsyncSession):
    oauth_user = User(
        email="oauth_no_pw@test.com",
        provider=UserProvider.GOOGLE,
        email_verified=True,
    )
    db_session.add(oauth_user)
    await db_session.commit()
    await db_session.refresh(oauth_user)

    raw, _ = await _create_reset_token(db_session, oauth_user.id)

    resp = await client.post(
        f"{BASE}/reset-password",
        json={"token": raw, "new_password": "NewPass99!"},
    )
    assert resp.status_code == 400
