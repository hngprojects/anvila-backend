from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import settings

pwd_hash = PasswordHash.recommended()


def create_token(
    payload: dict[str, Any],
    expires: timedelta,
    purpose: str | None = None,
) -> str:
    """Sign a JWT with an expiry. Caller supplies all claims except `iat`/`exp`."""
    now = datetime.now(UTC)
    data = {**payload, "iat": now, "exp": now + expires}
    if purpose is not None:
        data["purpose"] = purpose
    return jwt.encode(data, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_purpose: str | None = None) -> dict[str, Any]:
    """
    Decode and validate a JWT.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if expected_purpose is not None and payload.get("purpose") != expected_purpose:
        raise HTTPException(
            status_code=401,
            detail="Invalid token purpose",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def create_access_token(user_id: str) -> str:
    return create_token(
        {"sub": user_id},
        expires=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        purpose="access",
    )


def hash_password(password: str) -> str:
    return pwd_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_hash.verify(password, password_hash)
    except UnknownHashError:
        return False
