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
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        path=COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


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
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google token exchange failed",
            ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token exchange failed",
        )

    return response.json()


async def fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                settings.GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google userinfo request failed",
            ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google userinfo request failed",
        )

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
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            user = await get_user_by_google_subject(db, str(subject))
            if user is None:
                user = await get_user_by_email(db, email)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Account already exists",
                ) from exc
            _apply_google_profile(user, str(subject), profile, google_verified)
            try:
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Account already exists",
                ) from exc

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
    