import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse

from app.cache.redis import redis_client
from app.core.config import settings
from app.schemas.auth import UserResponse
from app.services.auth import clear_oauth_state_cookie

OTT_TTL = 60
OTT_KEY_PREFIX = "oauth:ott:"


@dataclass
class OTTEntry:
    access_token: str
    raw_refresh: str
    user: UserResponse | None = None


def _ott_key(code: str) -> str:
    return f"{OTT_KEY_PREFIX}{code}"


def _serialize_ott(entry: OTTEntry) -> str:
    payload = {
        "access_token": entry.access_token,
        "raw_refresh": entry.raw_refresh,
        "user": entry.user.model_dump(mode="json") if entry.user else None,
    }
    return json.dumps(payload)


def _deserialize_ott(raw: str) -> OTTEntry:
    payload = json.loads(raw)

    user_payload = payload.get("user")
    user = UserResponse.model_validate(user_payload) if user_payload else None

    return OTTEntry(
        access_token=payload["access_token"],
        raw_refresh=payload["raw_refresh"],
        user=user,
    )


async def create_ott(access_token: str, raw_refresh: str, user: UserResponse | None) -> str:
    code = secrets.token_urlsafe(32)

    entry = OTTEntry(
        access_token=access_token,
        raw_refresh=raw_refresh,
        user=user,
    )

    await redis_client.set(
        name=_ott_key(code),
        value=_serialize_ott(entry),
        ex=OTT_TTL,
    )

    return code


async def consume_ott(code: str) -> OTTEntry | None:
    key = _ott_key(code)

    async with redis_client.pipeline(transaction=True) as pipe:
        raw, _ = await pipe.get(key).delete(key).execute()

    if raw is None:
        return None

    return _deserialize_ott(raw)


async def redirect_with_ott(
    access_token: str, raw_refresh: str, user: UserResponse | None
) -> RedirectResponse:
    ott = await create_ott(access_token, raw_refresh, user)
    params = urlencode({"ott": ott})
    url = f"{settings.FRONTEND_URL}/auth/oauth/callback?{params}"
    redirect = RedirectResponse(url, status_code=302)
    clear_oauth_state_cookie(redirect)
    return redirect
