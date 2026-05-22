import pytest
import httpx
from fastapi import HTTPException, status
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError

from app.models.enums import UserProvider
from app.services import auth as auth_service


def test_build_google_auth_url_contains_required_params():
    state = "test-state"

    url = auth_service.build_google_auth_url(state)

    assert "client_id=" in url
    assert "redirect_uri=" in url
    assert "response_type=code" in url
    assert "scope=" in url
    assert f"state={state}" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_set_oauth_state_cookie():
    response = Response()

    auth_service.set_oauth_state_cookie(response, "state-token")

    cookie = response.headers["set-cookie"]

    assert "oauth_state=state-token" in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=600" in cookie
    assert "SameSite=lax" in cookie


def test_clear_oauth_state_cookie():
    response = Response()

    auth_service.clear_oauth_state_cookie(response)

    cookie = response.headers["set-cookie"]

    assert "oauth_state=" in cookie
    assert "Max-Age=0" in cookie


@pytest.mark.asyncio
async def test_exchange_google_code_success(monkeypatch):
    async def mock_post(self, url, data=None, headers=None):
        return httpx.Response(
            status_code=200,
            json={"access_token": "google-access-token"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await auth_service.exchange_google_code("google-code")

    assert result["access_token"] == "google-access-token"


@pytest.mark.asyncio
async def test_exchange_google_code_google_error(monkeypatch):
    async def mock_post(self, url, data=None, headers=None):
        return httpx.Response(
            status_code=400,
            json={"error": "invalid_grant"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with pytest.raises(HTTPException) as exc:
        await auth_service.exchange_google_code("bad-code")

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_exchange_google_code_network_error(monkeypatch):
    async def mock_post(self, url, data=None, headers=None):
        raise httpx.ConnectTimeout("connection timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with pytest.raises(HTTPException) as exc:
        await auth_service.exchange_google_code("google-code")

    assert exc.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc.value.detail == "Unable to reach Google OAuth service"


@pytest.mark.asyncio
async def test_fetch_google_userinfo_success(monkeypatch):
    async def mock_get(self, url, headers=None):
        return httpx.Response(
            status_code=200,
            json={
                "sub": "google-sub",
                "email": "test@example.com",
                "name": "Test User",
                "picture": "https://example.com/avatar.png",
                "email_verified": True,
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await auth_service.fetch_google_userinfo("google-access-token")

    assert result["sub"] == "google-sub"
    assert result["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_fetch_google_userinfo_network_error(monkeypatch):
    async def mock_get(self, url, headers=None):
        raise httpx.ConnectTimeout("connection timeout")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    with pytest.raises(HTTPException) as exc:
        await auth_service.fetch_google_userinfo("google-access-token")

    assert exc.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc.value.detail == "Unable to reach Google OAuth service"


def test_apply_google_profile_links_user():
    class User:
        google_subject = None
        provider = UserProvider.EMAIL
        display_name = None
        avatar_url = None
        email_verified = False

    user = User()

    auth_service._apply_google_profile(
        user=user,
        subject="google-sub",
        profile={
            "name": "Test User",
            "picture": "https://example.com/avatar.png",
        },
        google_verified=True,
    )

    assert user.google_subject == "google-sub"
    assert user.provider == UserProvider.GOOGLE
    assert user.display_name == "Test User"
    assert user.avatar_url == "https://example.com/avatar.png"
    assert user.email_verified is True


def test_apply_google_profile_rejects_different_google_subject():
    class User:
        google_subject = "old-google-sub"
        provider = UserProvider.GOOGLE
        display_name = None
        avatar_url = None
        email_verified = False

    user = User()

    with pytest.raises(HTTPException) as exc:
        auth_service._apply_google_profile(
            user=user,
            subject="new-google-sub",
            profile={},
            google_verified=True,
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
