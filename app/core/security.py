from typing import Any
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

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
