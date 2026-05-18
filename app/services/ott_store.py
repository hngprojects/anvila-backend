import asyncio
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.schemas.auth import UserResponse
from app.services.auth import clear_oauth_state_cookie

# TODO: use redis
OTT_TTL = 60


@dataclass
class OTTEntry:
    access_token: str
    raw_refresh: str
    user: UserResponse | None = None


_store: dict[str, OTTEntry] = {}


async def create_ott(access_token: str, raw_refresh: str, user: UserResponse | None) -> str:
    code = secrets.token_urlsafe(32)
    _store[code] = OTTEntry(access_token=access_token, raw_refresh=raw_refresh, user=user)
    asyncio.get_event_loop().call_later(OTT_TTL, _store.pop, code, None)
    return code


async def consume_ott(code: str) -> OTTEntry | None:
    return _store.pop(code, None)


async def redirect_with_ott(
    access_token: str, raw_refresh: str, user: UserResponse | None
) -> RedirectResponse:
    ott = await create_ott(access_token, raw_refresh, user)
    params = urlencode({"ott": ott})
    url = f"{settings.FRONTEND_URL}/auth/oauth/callback?{params}"
    redirect = RedirectResponse(url, status_code=302)
    clear_oauth_state_cookie(redirect)
    return redirect
