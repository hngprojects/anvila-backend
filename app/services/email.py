import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_verification_email(email: str, verification_url: str) -> None:
    """
    Send email verification link to a newly registered user.
    Stub: logs to stdout in dev.
    Replace body with real Brevo call when BREVO_API_KEY is set.
    """
    if settings.BREVO_API_KEY:
        try:
            # TODO: wire up sib-api-v3-sdk when ready
            # import sib_api_v3_sdk
            # configuration = sib_api_v3_sdk.Configuration()
            # configuration.api_key["api-key"] = settings.BREVO_API_KEY
            # ...
            logger.info("[EMAIL] Verification email queued for %s", email)
        except Exception as exc:
            logger.error(
                "[EMAIL] Failed to send verification email to %s: %s",
                email,
                exc,
            )
    else:
        print(
            f"[DEV] Verify email link for {email}: {verification_url}",
            flush=True,
        )


async def send_password_reset_email(email: str, reset_url: str) -> None:
    """
    Send password reset link.
    Stub: logs to stdout in dev.
    Replace body with real Brevo call when BREVO_API_KEY is set.
    """
    if settings.BREVO_API_KEY:
        try:
            logger.info("[EMAIL] Password reset email queued for %s", email)
        except Exception as exc:
            logger.error(
                "[EMAIL] Failed to send password reset email to %s: %s",
                email,
                exc,
            )
    else:
        print(
            f"[DEV] Password reset link for {email}: {reset_url}",
            flush=True,
        )


async def send_welcome_email(email: str, display_name: str = "") -> None:
    """
    Send welcome email after successful verification.
    Stub: logs to stdout in dev.
    """
    if settings.BREVO_API_KEY:
        try:
            logger.info("[EMAIL] Welcome email queued for %s", email)
        except Exception as exc:
            logger.error(
                "[EMAIL] Failed to send welcome email to %s: %s",
                email,
                exc,
            )
    else:
        print(
            f"[DEV] Welcome email for {email} ({display_name})",
            flush=True,
        )
