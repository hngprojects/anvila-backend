import pytest
from unittest.mock import patch

import app.services.email as email_module
from app.services.email import (
    send_password_reset_email,
    send_verification_email,
    send_welcome_email,
)


class _NoKeySettings:
    BREVO_API_KEY = ""


class _WithKeySettings:
    BREVO_API_KEY = "test-api-key"


# ---------------------------------------------------------------------------
# Stub mode (no API key) — functions must complete without raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_verification_email_stub_no_api_key(monkeypatch):
    monkeypatch.setattr(email_module, "settings", _NoKeySettings())
    await send_verification_email("test@example.com", "http://example.com/verify")


@pytest.mark.asyncio
async def test_send_password_reset_email_stub_no_api_key(monkeypatch):
    monkeypatch.setattr(email_module, "settings", _NoKeySettings())
    await send_password_reset_email("test@example.com", "http://example.com/reset")


@pytest.mark.asyncio
async def test_send_welcome_email_stub_no_api_key(monkeypatch):
    monkeypatch.setattr(email_module, "settings", _NoKeySettings())
    await send_welcome_email("test@example.com", "Test User")


# ---------------------------------------------------------------------------
# Never-raises guarantee — exceptions inside try block must be swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_verification_email_never_raises(monkeypatch):
    monkeypatch.setattr(email_module, "settings", _WithKeySettings())
    with patch.object(email_module.logger, "info", side_effect=Exception("boom")):
        await send_verification_email("test@example.com", "http://example.com/verify")


@pytest.mark.asyncio
async def test_send_password_reset_email_never_raises(monkeypatch):
    monkeypatch.setattr(email_module, "settings", _WithKeySettings())
    with patch.object(email_module.logger, "info", side_effect=Exception("boom")):
        await send_password_reset_email("test@example.com", "http://example.com/reset")


@pytest.mark.asyncio
async def test_send_welcome_email_never_raises(monkeypatch):
    monkeypatch.setattr(email_module, "settings", _WithKeySettings())
    with patch.object(email_module.logger, "info", side_effect=Exception("boom")):
        await send_welcome_email("test@example.com", "Test User")


# ---------------------------------------------------------------------------
# Stdout output in stub mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verification_email_prints_url_in_stub_mode(monkeypatch, capsys):
    monkeypatch.setattr(email_module, "settings", _NoKeySettings())
    await send_verification_email("a@b.com", "http://verify-url")
    captured = capsys.readouterr()
    assert "http://verify-url" in captured.out
    assert "a@b.com" in captured.out


@pytest.mark.asyncio
async def test_password_reset_email_prints_url_in_stub_mode(monkeypatch, capsys):
    monkeypatch.setattr(email_module, "settings", _NoKeySettings())
    await send_password_reset_email("a@b.com", "http://reset-url")
    captured = capsys.readouterr()
    assert "http://reset-url" in captured.out
    assert "a@b.com" in captured.out
