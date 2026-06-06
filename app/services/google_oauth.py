import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token_for_user
from app.models.enums import UserProvider
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth import get_user_by_email, get_user_by_google_subject


def build_google_auth_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.GOOGLE_SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{settings.GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_google_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(
                settings.GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text,
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach Google OAuth service",
            ) from exc

    return response.json()


async def fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                settings.GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text,
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach Google OAuth service",
            ) from exc

    return response.json()


async def login_or_register_google_user(
    db: AsyncSession,
    profile: dict[str, Any],
    request: Request,
) -> tuple[str, str, User]:
    subject = profile.get("sub")
    email = profile.get("email")

    if not subject or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google profile missing required fields",
        )

    email = str(email).lower()
    google_verified = bool(profile.get("email_verified"))

    user = await get_user_by_google_subject(db, str(subject))

    if user is None:
        user = await get_user_by_email(db, email)

        if user:
            _apply_google_profile(user, str(subject), profile, google_verified)
        else:
            user = User(
                email=email,
                display_name=profile.get("name"),
                avatar_url=profile.get("picture"),
                provider=UserProvider.GOOGLE,
                email_verified=google_verified,
                is_active=True,
                google_subject=str(subject),
            )
            db.add(user)

        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            user = await get_user_by_google_subject(db, str(subject))
            if user is None:
                user = await get_user_by_email(db, email)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to resolve user after concurrent OAuth registration",
                ) from exc
            _apply_google_profile(user, str(subject), profile, google_verified)
            try:
                await db.flush()
            except IntegrityError as inner_exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Google account already linked to another user",
                ) from inner_exc

        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    access_token = create_access_token_for_user(user)
    raw_refresh = secrets.token_urlsafe(32)
    refresh_token_record = RefreshToken(
        token_hash=hashlib.sha256(raw_refresh.encode()).hexdigest(),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(refresh_token_record)
    await db.commit()

    return access_token, raw_refresh, user


def _apply_google_profile(
    user: User,
    subject: str,
    profile: dict[str, Any],
    google_verified: bool,
) -> None:
    if user.google_subject and user.google_subject != subject:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Google account already linked",
        )
    user.google_subject = str(subject)
    if user.provider != UserProvider.GOOGLE:
        user.provider = UserProvider.GOOGLE
    if profile.get("name") and not user.display_name:
        user.display_name = str(profile["name"])
    if profile.get("picture") and not user.avatar_url:
        user.avatar_url = str(profile["picture"])
    if google_verified:
        user.email_verified = True
