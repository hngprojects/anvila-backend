import logging
from functools import partial

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt
from app.models.enums import PaymentStatus
from app.models.payment_transaction import PaymentTransaction
from app.models.persona import Persona, PersonaStatus, PersonaVisibility
from app.models.user import User
from app.services.publishing.github import create_user_repo, upsert_user_file
from app.services.publishing.utils import (
    get_persona_skills,
    persist_persona,
    push_files,
    push_skills,
)
from app.utils.slugify import slugify

logger = logging.getLogger(__name__)
GITHUB_API = "https://api.github.com"


async def _resolve_username(token: str, fallback: str | None) -> str:
    """Use stored username if available, otherwise fetch from GitHub."""
    if fallback:
        return fallback
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
    if not resp.is_success:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch GitHub username")
    return resp.json()["login"]


async def publish_persona_private(persona: Persona, user: User, db: AsyncSession) -> Persona:
    """Publish a persona to the user's own private GitHub repo."""
    if (
        persona.status == PersonaStatus.PUBLISHED
        and persona.visibility == PersonaVisibility.PRIVATE
    ):
        logger.info("persona %s already privately published, skipping", persona.id)
        return persona

    if persona.status != PersonaStatus.GENERATED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Persona must be GENERATED before publishing (current: {persona.status})",
        )

    # payment gate
    paid = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.user_id == user.id,
            PaymentTransaction.status == PaymentStatus.SUCCEEDED,
        )
    )
    if not paid:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "payment_required",
                "message": "A one-time payment is required to unlock private publishing.",
            },
        )

    # github connection gate
    if not user.github_connected or not user.github_access_token_encrypted:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "github_not_connected",
                "message": "Connect your GitHub account before private publishing.",
            },
        )

    token = decrypt(user.github_access_token_encrypted)
    username = await _resolve_username(token, user.github_username)
    slug = slugify(persona.name)

    repo = await create_user_repo(
        slug=slug,
        description=(persona.description_summary or f"Persona: {persona.name}")[:255],
        token=token,
    )

    # partial bakes username + token into the upsert signature → (path, content, message)
    upsert = partial(upsert_user_file, username, slug, token=token)

    skills = await get_persona_skills(persona.id, db)
    await push_files(persona, upsert)
    await push_skills(skills, upsert)
    await persist_persona(persona, repo, PersonaVisibility.PRIVATE, db)

    logger.info(
        "event=persona.publish.private persona_id=%s repo=%s user_id=%s skills=%d",
        persona.id,
        persona.github_repo_url,
        user.id,
        len(skills),
    )
    return persona
