import logging
from pathlib import Path

import sib_api_v3_sdk
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sib_api_v3_sdk.configuration import Configuration
from sib_api_v3_sdk.rest import ApiException

from app.core.config import settings

logger = logging.getLogger(__name__)

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _render(template_name: str, **ctx) -> tuple[str, str]:
    """Render a template and its plain-text block. Returns (plain, html)."""
    template = _env.get_template(template_name)
    html = template.render(**ctx)
    plain = template.module.plain_text(**ctx)
    return plain, html


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str,
    to_name: str = "",
) -> None:
    """Core sender — everything funnels through here."""
    configuration = Configuration()
    configuration.api_key["api-key"] = settings.BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email, "name": to_name or to_email}],
        sender={"name": settings.SMTP_FROM_NAME, "email": settings.SMTP_FROM_EMAIL},
        subject=subject,
        html_content=html_body,
        text_content=plain_body,
    )
    try:
        api_instance.send_transac_email(send_smtp_email)
        logger.info("email sent | to=%s subject=%s", to_email, subject)
    except ApiException:
        logger.exception("email failed | to=%s subject=%s", to_email, subject)
        raise


def send_verification_email(email: str, url: str) -> None:
    plain, html = _render(
        "verification.html",
        email=email,
        verification_url=url,
        ttl_hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS,
    )
    send_email(email, "Verify your email address", html, plain)


def send_password_reset_email(email: str, reset_url: str) -> None:
    plain, html = _render("password_reset.html", email=email, reset_url=reset_url)
    send_email(email, "Reset your password", html, plain)


def send_oauth_link_email(email: str, link_url: str) -> None:
    plain, html = _render("oauth_link.html", email=email, link_url=link_url)
    send_email(email, "Connect your GitHub account", html, plain)


def send_contact_admin_notification(
    full_name: str, email: str, phone: str | None, message: str
) -> None:
    plain, html = _render(
        "contact_admin.html", full_name=full_name, email=email, phone=phone, message=message
    )
    send_email(
        to_email=settings.ADMIN_EMAIL,
        to_name="Admin",
        subject=f"New contact message from {full_name}",
        html_body=html,
        plain_body=plain,
    )
