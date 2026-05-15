from typing import Any
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
import secrets
from datetime import UTC, datetime, timedelta
import jwt
from app.core.config import settings

pwd_hash = PasswordHash.recommended()


def decode_token(token: str) -> dict[str, Any]:
    # TODO: Implement
    return {"user_id": 1}


def hash_password(password: str) -> str:
    return pwd_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_hash.verify(password, password_hash)
    except UnknownHashError:
        return False
    
def create_token(subject: str, purpose: str, expires_delta: timedelta) -> str:
    payload = {
        "sub": subject,
        "purpose": purpose,
        "exp": datetime.now(UTC) + expires_delta,
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_oauth_state_token() -> str:
    return create_token(
        subject=secrets.token_urlsafe(32),
        purpose="oauth_state",
        expires_delta=timedelta(minutes=10),
    )