from datetime import timedelta
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import urlencode
from typing import Any

import httpx
from fastapi import HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import create_token
from app.models.enums import UserProvider

from app.models.user import User

OAUTH_STATE_COOKIE = "oauth_state"
COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"
REFRESH_TOKEN_COOKIE = "refresh_token"
REFRESH_TOKEN_COOKIE_MAX_AGE = settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60

async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

async def get_user_by_google_subject(
    db: AsyncSession,
    subject: str,
) -> User | None:
    result = await db.execute(select(User).where(User.google_subject == subject))
    return result.scalar_one_or_none()    

def set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        max_age=REFRESH_TOKEN_COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )

def set_oauth_state_cookie(response: Response, state: str) -> None:
    """Store the OAuth state token in an HttpOnly cookie for callback validation."""
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=600,
        path=COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def clear_oauth_state_cookie(response: Response) -> None:
    """Remove the OAuth state cookie after the OAuth flow completes or fails."""
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        path=COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def build_google_auth_url(state: str) -> str:
    """Build the Google OAuth authorization URL with the required query parameters."""
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
    """Exchange a Google OAuth authorization code for a token response."""
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(
                settings.GOOGLE_TOKEN_URL,
                data=data,
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
    """Fetch the user's profile information from Google using the access token."""
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
    """Create or retrieve a Google-authenticated user and issue application tokens."""
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
            await db.commit()
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
            
            await db.commit()

        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    access_token, raw_refresh = await issue_auth_tokens(db, user, request)

    return access_token, raw_refresh, user

async def issue_auth_tokens(
    db: AsyncSession,
    user: User,
    request: Request,
) -> tuple[str, str]:
    access_token = create_access_token(subject=str(user.id))
    raw_refresh = create_refresh_token(subject=str(user.id))
    return access_token, raw_refresh

def create_access_token(subject: str) -> str:
    return create_token(
        subject=subject,
        purpose="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
    )

def create_refresh_token(subject: str) -> str:
    return create_token(
        subject=subject,
        purpose="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
    )

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
        user.display_name = str(profile.get("name"))
    if profile.get("picture") and not user.avatar_url:
        user.avatar_url = str(profile.get("picture"))
    if google_verified:
        user.email_verified = True
    