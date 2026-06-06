import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserProvider
from app.models.oauth_link_token import OAuthLinkToken
from app.models.user import User
from app.services.oauth_link import mint_link_token

BASE = "/api/v1/auth"
INVALID_LINK_DETAIL = "Invalid or expired link token"


async def _make_user(
    db: AsyncSession,
    *,
    email: str,
    is_active: bool = True,
    provider: UserProvider = UserProvider.EMAIL,
) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$dummy" if provider == UserProvider.EMAIL else None,
        display_name="Existing User",
        provider=provider,
        email_verified=True,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)
    return user


async def test_confirm_link_success(client: AsyncClient, db_session: AsyncSession):
    """Valid link token links the GitHub identity, mints tokens, and returns LoginData."""
    user = await _make_user(db_session, email="confirm_success@example.com")
    raw_token = await mint_link_token(
        db_session,
        user=user,
        provider="github",
        provider_subject="9001",
    )
    await db_session.commit()

    resp = await client.get(f"{BASE}/oauth/confirm-link", params={"token": raw_token})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["user"]["email"] == "confirm_success@example.com"
    assert body["data"]["tokens"]["access_token"]
    assert body["data"]["tokens"]["refresh_token"]
    assert body["data"]["tokens"]["token_type"] == "bearer"

    # Persistence: re-read user from a fresh session via test session.
    refreshed = await db_session.execute(select(User).where(User.id == user.id))
    refreshed_user = refreshed.scalar_one()
    assert refreshed_user.github_subject == "9001"
    assert refreshed_user.email_verified is True


async def test_confirm_link_marks_token_consumed(
    client: AsyncClient, db_session: AsyncSession
):
    """The link-token row's consumed_at is populated after a successful confirm."""
    user = await _make_user(db_session, email="consume_marker@example.com")
    raw_token = await mint_link_token(
        db_session,
        user=user,
        provider="github",
        provider_subject="9002",
    )
    await db_session.commit()

    resp = await client.get(f"{BASE}/oauth/confirm-link", params={"token": raw_token})
    assert resp.status_code == 200

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    row = (
        await db_session.execute(
            select(OAuthLinkToken).where(OAuthLinkToken.token_hash == token_hash)
        )
    ).scalar_one()
    assert row.consumed_at is not None


@pytest.mark.parametrize("scenario", ["unknown", "consumed", "expired"])
async def test_confirm_link_anti_enumeration(
    client: AsyncClient, db_session: AsyncSession, scenario: str
):
    """Unknown, consumed, and expired tokens all surface the same 400 response shape."""
    if scenario == "unknown":
        token = "this-token-does-not-exist-anywhere-12345"
    elif scenario == "consumed":
        user = await _make_user(db_session, email=f"{scenario}@example.com")
        token = await mint_link_token(
            db_session, user=user, provider="github", provider_subject="9100"
        )
        await db_session.commit()
        first = await client.get(f"{BASE}/oauth/confirm-link", params={"token": token})
        assert first.status_code == 200
    else:  # expired
        user = await _make_user(db_session, email=f"{scenario}@example.com")
        token = await mint_link_token(
            db_session, user=user, provider="github", provider_subject="9101"
        )
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = (
            await db_session.execute(
                select(OAuthLinkToken).where(OAuthLinkToken.token_hash == token_hash)
            )
        ).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db_session.flush()
        await db_session.commit()

    resp = await client.get(f"{BASE}/oauth/confirm-link", params={"token": token})
    assert resp.status_code == 400
    assert resp.json()["detail"] == INVALID_LINK_DETAIL
    assert "refresh_token=" not in resp.headers.get("set-cookie", "")


async def test_confirm_link_missing_user(client: AsyncClient, db_session: AsyncSession):
    """A link token whose user has been deleted surfaces the anti-enumeration 400."""
    user = await _make_user(db_session, email="missing_user@example.com")
    raw_token = await mint_link_token(
        db_session, user=user, provider="github", provider_subject="9200"
    )
    await db_session.commit()
    # Delete the user; the link-token row cascades on user delete, so the lookup
    # produces the anti-enumeration "Invalid or expired link token" path.
    await db_session.delete(user)
    await db_session.commit()

    resp = await client.get(f"{BASE}/oauth/confirm-link", params={"token": raw_token})
    assert resp.status_code == 400
    assert resp.json()["detail"] == INVALID_LINK_DETAIL
    assert "refresh_token=" not in resp.headers.get("set-cookie", "")


async def test_confirm_link_inactive_user(
    client: AsyncClient, db_session: AsyncSession
):
    """A confirm against an inactive user returns 403 and does not mint tokens."""
    user = await _make_user(
        db_session, email="inactive_confirm@example.com", is_active=False
    )
    raw_token = await mint_link_token(
        db_session, user=user, provider="github", provider_subject="9300"
    )
    await db_session.commit()

    resp = await client.get(f"{BASE}/oauth/confirm-link", params={"token": raw_token})

    assert resp.status_code == 403
    assert "refresh_token=" not in resp.headers.get("set-cookie", "")
