import time

from fastapi import status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded as SlowApiRateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


def limiter_key_func(request: Request) -> str:
    """
    Extract rate-limit key from request.
    """
    user = getattr(request.state, "user", None)
    if user is not None:
        return f"user:{user.id}"

    ip = get_remote_address(request)
    return f"ip:{ip}"


limiter = Limiter(
    key_func=limiter_key_func,
    storage_uri=settings.REDIS_URL,
    strategy="moving-window",
    headers_enabled=False,  # breaks endpoint that relies on middleware to build response
)


async def rate_limit_error_handler(
    request: Request,
    exc: Exception,  # widen exception to satisfy type checker
) -> Response:
    """
    FastAPI exception handler for rate limit violations.
    Returns 429 with Retry-After header.
    """

    rate_limit_exc = exc if isinstance(exc, SlowApiRateLimitExceeded) else None

    detail = rate_limit_exc.detail if rate_limit_exc else "unknown"

    response = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": f"Rate limit exceeded: {detail}"},
    )

    view_rate_limit = getattr(request.state, "view_rate_limit", None)
    if view_rate_limit is not None:
        limit_item, keys = view_rate_limit
        limiter: Limiter = request.app.state.limiter
        try:
            window_stats = limiter.limiter.get_window_stats(limit_item, *keys)
            reset_in = 1 + window_stats[0]
            response.headers["X-RateLimit-Limit"] = str(limit_item.amount)
            response.headers["X-RateLimit-Remaining"] = str(window_stats[1])
            response.headers["X-RateLimit-Reset"] = str(reset_in)
            response.headers["Retry-After"] = str(int(reset_in - time.time()))
        except Exception:
            pass
    return response
