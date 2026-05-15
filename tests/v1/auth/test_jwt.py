import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

import app.core.security as sec


SECRET = "test-secret-32-chars-padding-xxxx"
ALGORITHM = "HS256"


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    class FakeSettings:
        JWT_SECRET = SECRET
        JWT_ALGORITHM = ALGORITHM
        ACCESS_TOKEN_EXPIRE_MINUTES = 1440
        REFRESH_TOKEN_EXPIRE_DAYS = 7

    monkeypatch.setattr(sec, "settings", FakeSettings())


def test_create_access_token_contains_required_fields():
    token = sec.create_access_token({"sub": "user-uuid", "email": "a@b.com"})
    payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert payload["sub"] == "user-uuid"
    assert payload["email"] == "a@b.com"
    assert "exp" in payload
    assert payload["purpose"] == "access"


def test_create_refresh_token_contains_required_fields():
    token = sec.create_refresh_token({"sub": "user-uuid", "email": "a@b.com"})
    payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert payload["sub"] == "user-uuid"
    assert payload["email"] == "a@b.com"
    assert "exp" in payload
    assert payload["purpose"] == "refresh"
    expected_exp = datetime.now(timezone.utc) + timedelta(days=7)
    actual_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert abs((actual_exp - expected_exp).total_seconds()) < 5


def test_decode_token_valid():
    token = sec.create_access_token({"sub": "abc", "email": "x@y.com"})
    payload = sec.decode_token(token)
    assert payload["sub"] == "abc"
    assert payload["email"] == "x@y.com"
    assert payload["purpose"] == "access"


def test_decode_token_expired():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    token = jwt.encode(
        {"sub": "abc", "exp": past},
        SECRET,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        sec.decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_token_invalid_signature():
    token = jwt.encode({"sub": "abc"}, "wrong-secret-32-chars-paddingxxx", algorithm=ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        sec.decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_token_wrong_secret():
    token = sec.create_access_token({"sub": "abc"})
    tampered = token[:-4] + "XXXX"
    with pytest.raises(HTTPException) as exc_info:
        sec.decode_token(tampered)
    assert exc_info.value.status_code == 401


def test_access_token_expiry_is_24_hours():
    before = time.time()
    token = sec.create_access_token({"sub": "abc"})
    after = time.time()
    payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    # iat is not set explicitly; compare exp against when token was created
    expected_duration = 1440 * 60  # 86400 seconds
    # exp should be ~86400s after creation; allow 5s tolerance
    assert abs(payload["exp"] - (before + expected_duration)) < 5
    assert abs(payload["exp"] - (after + expected_duration)) < 5


def test_refresh_token_expiry_is_7_days():
    before = time.time()
    token = sec.create_refresh_token({"sub": "abc"})
    after = time.time()
    payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    expected_duration = 7 * 24 * 3600  # 604800 seconds
    assert abs(payload["exp"] - (before + expected_duration)) < 5
    assert abs(payload["exp"] - (after + expected_duration)) < 5
