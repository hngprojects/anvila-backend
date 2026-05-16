import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.enums import UserProvider
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    normalized = email.strip().lower()
    result = await db.execute(select(User).where(User.email == normalized))
    return result.scalar_one_or_none()


async def register_user(
    db: AsyncSession,
    email: str,
    password: str,
    display_name: str | None = None,
) -> tuple[User, str]:
    normalized_email = email.strip().lower()
    existing = await get_user_by_email(db, normalized_email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS
    )

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        display_name=display_name,
        provider=UserProvider.EMAIL,
        verification_token_hash=token_hash,
        verification_token_expires_at=expires_at,
    )
    db.add(user)
    await db.flush()

    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"
    return user, verification_url


async def verify_email(db: AsyncSession, raw_token: str) -> User:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    result = await db.execute(select(User).where(User.verification_token_hash == token_hash))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already verified",
        )
    if (
        user.verification_token_expires_at is None
        or user.verification_token_expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token has expired",
        )

    user.email_verified = True
    user.verification_token_hash = None
    user.verification_token_expires_at = None
    await db.flush()

    return user


async def resend_verification_email(db: AsyncSession, email: str) -> str | None:
    """Returns the verification URL to send, or None if the account is unknown/inactive."""
    user = await get_user_by_email(db, email)
    if user is None or not user.is_active:
        return None

    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already verified",
        )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS
    )

    user.verification_token_hash = token_hash
    user.verification_token_expires_at = expires_at
    await db.flush()

    return f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"


async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str]:
    user = await get_user_by_email(db, email.strip().lower())
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    access_token = create_access_token({"sub": str(user.id)})
    raw_refresh = secrets.token_urlsafe(32)
    refresh_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()

    refresh_token_record = RefreshToken(
        token_hash=refresh_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(refresh_token_record)
    await db.flush()

    return access_token, raw_refresh


async def refresh_access_token(
    db: AsyncSession,
    raw_refresh_token: str,
) -> str:
    # Refresh tokens are opaque random strings (not JWTs) — hash and look up in DB.
    token_hash = hashlib.sha256(raw_refresh_token.encode()).hexdigest()
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    token_record = result.scalar_one_or_none()

    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found"
        )
    if token_record.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked"
        )
    if token_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired"
        )

    user = await get_user_by_id(db, token_record.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return create_access_token({"sub": str(user.id)})


async def logout_user(
    db: AsyncSession,
    raw_refresh_token: str,
) -> None:
    token_hash = hashlib.sha256(raw_refresh_token.encode()).hexdigest()
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    token_record = result.scalar_one_or_none()

    if token_record and not token_record.revoked:
        token_record.revoked = True
        await db.flush()


async def create_password_reset_token(
    db: AsyncSession,
    email: str,
) -> str | None:
    user = await get_user_by_email(db, email)

    if not user:
        return None

    # Gap 2: OAuth users have no password — silently skip
    if user.provider != UserProvider.EMAIL:
        return None

    if not user.password_hash:
        return None

    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)
    await db.commit()

    return raw


async def reset_password(
    db: AsyncSession,
    raw_token: str,
    new_password: str,
) -> bool:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_record = result.scalar_one_or_none()

    if not token_record:
        return False

    if token_record.used_at is not None:
        return False

    if token_record.expires_at < datetime.now(timezone.utc):
        return False

    user = await get_user_by_id(db, token_record.user_id)
    if not user:
        return False

    if not user.password_hash:
        return False

    user.password_hash = hash_password(new_password)
    token_record.used_at = datetime.now(timezone.utc)

    # Gap 3: Revoke all active refresh tokens on password change
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id)
        .where(RefreshToken.revoked == False)  # noqa: E712
        .values(revoked=True)
    )

    await db.commit()
    return True
