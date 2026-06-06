import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.oauth_link_token import OAuthLinkToken
from app.models.user import User

_INVALID_LINK_TOKEN_DETAIL = "Invalid or expired link token"


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def mint_link_token(
    db: AsyncSession,
    *,
    user: User,
    provider: str,
    provider_subject: str,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.OAUTH_LINK_TOKEN_EXPIRE_MINUTES
    )

    row = OAuthLinkToken(
        user_id=user.id,
        provider=provider,
        provider_subject=provider_subject,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()

    return raw_token


async def consume_link_token(db: AsyncSession, raw_token: str) -> OAuthLinkToken:
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(OAuthLinkToken)
        .where(OAuthLinkToken.token_hash == token_hash)
        .with_for_update()
    )
    row = result.scalar_one_or_none()

    # Anti-enumeration: not-found, consumed, and expired all surface the same shape.
    if row is None or row.consumed_at is not None or row.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_LINK_TOKEN_DETAIL,
        )

    row.consumed_at = datetime.now(UTC)
    await db.flush()
    return row
