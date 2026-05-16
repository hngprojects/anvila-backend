import logging

_log = logging.getLogger(__name__)


def send_verification_email(email: str, verification_url: str) -> None:
    _log.debug("[DEV] Verification email dispatched (recipient redacted)")


def send_password_reset_email(email: str, reset_url: str) -> None:
    _log.debug("[DEV] Password reset email dispatched (recipient redacted)")
