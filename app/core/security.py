from typing import Any
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
import secrets
from datetime import UTC, datetime, timedelta
import jwt
from fastapi import HTTPException, status
from app.core.config import settings

pwd_hash = PasswordHash.recommended()


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )

        return payload

    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


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
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_oauth_state_token() -> str:
    return create_token(
        subject=secrets.token_urlsafe(32),
        purpose="oauth_state",
        expires_delta=timedelta(minutes=10),
    )