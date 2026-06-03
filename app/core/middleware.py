import uuid

from fastapi import Request

from app.core.security import decode_token
from app.db.session import AsyncSessionLocal
from app.services.auth import get_user_by_id


async def attach_user_to_request(request: Request, call_next):
    request.state.current_user = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            payload = decode_token(token, expected_purpose="access")
            user_id = uuid.UUID(payload["sub"])
            async with AsyncSessionLocal() as db:
                user = await get_user_by_id(db, user_id)
                if user and user.is_active:
                    request.state.current_user = user
        except Exception:
            pass
    return await call_next(request)
