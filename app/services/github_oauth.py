import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.enums import UserProvider
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth import (
    get_user_by_email,
    get_user_by_github_subject,
    revoke_all_active_refresh_tokens,
)
from app.services.oauth_link import mint_link_token

GITHUB_LINK_CONFIRMATION_PATH = "/api/v1/auth/oauth/confirm-link"
_GITHUB_PROVIDER = "github"

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LoginCompleted:
    access_token: str
    raw_refresh: str
    user: User


@dataclass(slots=True)
class LinkConfirmationRequired:
    email: str
    link_token: str
    user_id: UUID
    github_subject: str


CallbackOutcome = LoginCompleted | LinkConfirmationRequired


def _make_async_client(*, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    if transport is not None:
        return httpx.AsyncClient(timeout=10, transport=transport)
    return httpx.AsyncClient(timeout=10)


def _hash_email_for_log(email: str | None) -> str:
    if not email:
        return "-"
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


def build_github_auth_url(state: str) -> str:
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
        "scope": settings.GITHUB_SCOPES,
        "state": state,
        "response_type": "code",
        "allow_signup": "true",
    }
    return f"{settings.GITHUB_AUTH_URL}?{urlencode(params)}"


async def exchange_github_code(
    code: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    async with _make_async_client(transport=transport) as client:
        try:
            response = await client.post(
                settings.GITHUB_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "redirect_uri": settings.GITHUB_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Never echo provider body to caller — replicating Google's leak is unsafe.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub token exchange failed",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub token exchange failed",
            ) from exc

    return response.json()


async def fetch_github_profile(
    access_token: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    async with _make_async_client(transport=transport) as client:
        try:
            response = await client.get(
                settings.GITHUB_USERINFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub profile fetch failed",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub profile fetch failed",
            ) from exc

    return response.json()


async def fetch_github_verified_emails(
    access_token: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    async with _make_async_client(transport=transport) as client:
        try:
            response = await client.get(
                settings.GITHUB_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub email fetch failed",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub email fetch failed",
            ) from exc

    payload = response.json()
    return payload if isinstance(payload, list) else []


def resolve_primary_verified_email(emails: list[dict[str, Any]]) -> str | None:
    primary_verified = next(
        (entry.get("email") for entry in emails if entry.get("primary") and entry.get("verified")),
        None,
    )
    if primary_verified:
        return str(primary_verified).lower()

    any_verified = next(
        (entry.get("email") for entry in emails if entry.get("verified")),
        None,
    )
    return str(any_verified).lower() if any_verified else None


async def _mint_session_tokens(
    db: AsyncSession,
    *,
    user: User,
    request: Request,
) -> tuple[str, str]:
    # Q9: rotate refresh tokens on every successful OAuth login.
    await revoke_all_active_refresh_tokens(db, user.id)

    access_token = create_access_token(str(user.id))
    raw_refresh = secrets.token_urlsafe(32)
    refresh_record = RefreshToken(
        token_hash=hashlib.sha256(raw_refresh.encode()).hexdigest(),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(refresh_record)
    await db.flush()
    return access_token, raw_refresh


def _apply_github_profile_fields(
    user: User,
    *,
    subject: str,
    profile: dict[str, Any],
) -> None:
    user.github_subject = subject
    if user.provider != UserProvider.GITHUB:
        user.provider = UserProvider.GITHUB
    login = profile.get("login")
    if login:
        user.github_username = str(login)
    if profile.get("name") and not user.display_name:
        user.display_name = str(profile["name"])
    if profile.get("avatar_url") and not user.avatar_url:
        user.avatar_url = str(profile["avatar_url"])
    user.email_verified = True


async def process_github_callback(
    db: AsyncSession,
    *,
    code: str,
    request: Request,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CallbackOutcome:
    _logger.info(
        "event=auth.oauth.github.callback.start outcome=pending",
    )

    token_payload = await exchange_github_code(code, transport=transport)
    github_access_token = token_payload.get("access_token")
    if not github_access_token:
        _logger.warning(
            "event=auth.oauth.github.callback.error outcome=no_access_token",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub token response missing access token",
        )

    profile = await fetch_github_profile(github_access_token, transport=transport)
    subject_raw = profile.get("id")
    if subject_raw is None:
        _logger.warning(
            "event=auth.oauth.github.callback.error outcome=no_profile_id",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub profile missing id",
        )
    subject = str(subject_raw)

    emails = await fetch_github_verified_emails(github_access_token, transport=transport)
    verified_email = resolve_primary_verified_email(emails)
    if not verified_email:
        _logger.warning(
            "event=auth.oauth.github.callback.error outcome=no_verified_email",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub account has no verified email",
        )

    email_hash = _hash_email_for_log(verified_email)

    existing_by_subject = await get_user_by_github_subject(db, subject)
    if existing_by_subject is not None:
        if not existing_by_subject.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )
        access_token, raw_refresh = await _mint_session_tokens(
            db, user=existing_by_subject, request=request
        )
        _logger.info(
            "event=auth.oauth.github.callback.success outcome=returning_user "
            "user_id=%s email_hash=%s",
            existing_by_subject.id,
            email_hash,
        )
        return LoginCompleted(
            access_token=access_token,
            raw_refresh=raw_refresh,
            user=existing_by_subject,
        )

    existing_by_email = await get_user_by_email(db, verified_email)
    if existing_by_email is not None:
        if not existing_by_email.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )
        existing_by_email.github_subject = subject
        existing_by_email.github_username = str(profile["login"]) if profile.get("login") else None
        await db.flush()
        access_token, raw_refresh = await _mint_session_tokens(
            db, user=existing_by_email, request=request
        )
        _logger.info(
            "event=auth.oauth.github.link_pending outcome=link_required user_id=%s email_hash=%s",
            existing_by_email.id,
            email_hash,
        )
        return LoginCompleted(
            access_token=access_token,
            raw_refresh=raw_refresh,
            user=existing_by_email,
        )

    new_user = User(
        email=verified_email,
        display_name=profile.get("name"),
        avatar_url=profile.get("avatar_url"),
        provider=UserProvider.GITHUB,
        email_verified=True,
        is_active=True,
        github_subject=subject,
        github_username=str(profile["login"]) if profile.get("login") else None,
    )
    db.add(new_user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        resolved = await get_user_by_github_subject(db, subject)
        if resolved is None:
            resolved = await get_user_by_email(db, verified_email)
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resolve user after concurrent OAuth registration",
            ) from exc
        # Concurrent racer won. If it already owns this subject, log them in.
        if resolved.github_subject == subject:
            if not resolved.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is disabled",
                ) from exc
            access_token, raw_refresh = await _mint_session_tokens(
                db, user=resolved, request=request
            )
            _logger.info(
                "event=auth.oauth.github.callback.success outcome=race_resolved "
                "user_id=%s email_hash=%s",
                resolved.id,
                email_hash,
            )
            return LoginCompleted(
                access_token=access_token,
                raw_refresh=raw_refresh,
                user=resolved,
            )
        # Racer holds the email but a different (or no) github_subject -> link flow.
        if not resolved.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            ) from exc
        link_token = await mint_link_token(
            db,
            user=resolved,
            provider=_GITHUB_PROVIDER,
            provider_subject=subject,
        )
        _logger.info(
            "event=auth.oauth.github.link_pending outcome=link_required_race "
            "user_id=%s email_hash=%s",
            resolved.id,
            email_hash,
        )
        return LinkConfirmationRequired(
            email=verified_email,
            link_token=link_token,
            user_id=resolved.id,
            github_subject=subject,
        )

    access_token, raw_refresh = await _mint_session_tokens(db, user=new_user, request=request)
    _logger.info(
        "event=auth.oauth.github.callback.success outcome=new_user user_id=%s email_hash=%s",
        new_user.id,
        email_hash,
    )
    return LoginCompleted(
        access_token=access_token,
        raw_refresh=raw_refresh,
        user=new_user,
    )


# Helper consumed by routes after `consume_link_token` validates the token.
def apply_github_link(user: User, *, github_subject: str, github_username: str | None) -> None:
    user.github_subject = github_subject
    if github_username:
        user.github_username = github_username
    user.email_verified = True
