import pytest
from pydantic import ValidationError

from app.core.config import Settings

_REQUIRED_NON_GITHUB = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/anvila_validation_test",
    "JWT_SECRET": "test-secret-key-minimum-32-characters-long-x",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
    "GOOGLE_CLIENT_SECRET": "test-google-client-secret",
    "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/v1/auth/google/callback",
}

_GITHUB_VARS = ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_REDIRECT_URI")


def test_settings_boot_succeeds_when_flag_off_and_creds_unset(monkeypatch):
    for var in _GITHUB_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GITHUB_OAUTH_ENABLED", "false")

    s = Settings(_env_file=None, **_REQUIRED_NON_GITHUB)

    assert s.GITHUB_CLIENT_ID is None
    assert s.GITHUB_CLIENT_SECRET is None
    assert s.GITHUB_REDIRECT_URI is None
    assert s.GITHUB_OAUTH_ENABLED is False


def test_settings_boot_fails_when_flag_on_and_creds_missing(monkeypatch):
    for var in _GITHUB_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GITHUB_OAUTH_ENABLED", "true")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **_REQUIRED_NON_GITHUB)

    message = str(exc_info.value)
    for var in _GITHUB_VARS:
        assert var in message
