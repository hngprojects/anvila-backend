import json
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.db.redis import get_redis
from app.schemas.auth import UserResponse
from app.services.auth import clear_oauth_state_cookie

logger = logging.getLogger(__name__)

OTT_TTL = 60
OTT_PREFIX = "ott:"


@dataclass
class OTTEntry:
    access_token: str
    raw_refresh: str
    user: UserResponse | None = None


_store: dict[str, OTTEntry] = {}


# async def create_ott(access_token: str, raw_refresh: str, user: UserResponse | None) -> str:
#     code = secrets.token_urlsafe(32)
#     _store[code] = OTTEntry(access_token=access_token, raw_refresh=raw_refresh, user=user)
#     asyncio.get_event_loop().call_later(OTT_TTL, _store.pop, code, None)
#     return code


async def create_ott(access_token: str, raw_refresh: str, user: UserResponse | None) -> str:
    redis_client = get_redis()
    code = secrets.token_urlsafe(32)
    payload = {
        "access_token": access_token,
        "raw_refresh": raw_refresh,
        "user": user.model_dump(mode="json") if user else None,
    }
    await redis_client.set(f"{OTT_PREFIX}{code}", json.dumps(payload), ex=OTT_TTL)
    return code


async def consume_ott(code: str) -> OTTEntry | None:
    """Fetch and atomically delete the OTT — truly single use."""
    redis_client = get_redis()
    key = f"{OTT_PREFIX}{code}"
    try:
        # GETDEL atomically gets and deletes — no race condition
        raw = await redis_client.getdel(key)
        if raw is None:
            return None
        data = json.loads(raw)
        user = UserResponse.model_validate(data["user"]) if data.get("user") else None
        return OTTEntry(
            access_token=data["access_token"],
            raw_refresh=data["raw_refresh"],
            user=user,
        )
    except Exception:
        redacted = f"{code[:6]}..." if code else "none"
        logger.exception("consume_ott failed code=%s", redacted)
        return None


# async def consume_ott(code: str) -> OTTEntry | None:
#     return _store.pop(code, None)


async def redirect_with_ott(
    access_token: str, raw_refresh: str, user: UserResponse | None
) -> RedirectResponse:
    ott = await create_ott(access_token, raw_refresh, user)
    params = urlencode({"ott": ott})
    url = f"{settings.FRONTEND_URL}/auth/oauth/callback?{params}"
    redirect = RedirectResponse(url, status_code=302)
    clear_oauth_state_cookie(redirect)
    return redirect
