import logging

_log = logging.getLogger(__name__)


async def send_verification_email(email: str, verification_url: str) -> None:
    _log.debug("[DEV] Verification email dispatched (recipient redacted)")
