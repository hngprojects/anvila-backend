# app/services/private_publish.py
import logging

import httpx
from app.models.payment_transaction import PaymentTransaction
from app.services.github_user import (
    create_or_get_user_repo,
    upsert_user_file,
)
from app.services.publish import _get_persona_skills  # reuse existing helper
from app.utils.skills import build_skill_md, is_safe_skill_slug, safe_skill_files
from fastapi import HTTPException, status
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt  # your existing helper
from app.models.enums import PaymentStatus
from app.models.persona import Persona, PersonaStatus

GITHUB_API = "https://api.github.com"
_logger = logging.getLogger(__name__)


async def _get_github_username(token: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    if not resp.is_success:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch GitHub user info")
    return resp.json()["login"]


async def publish_persona_private(persona: Persona, user, db: AsyncSession) -> Persona:
    """
    Publish a persona to the user's own GitHub account as a private repo.
    Guards: must have paid + must have GitHub connected.
    If already privately published, skip silently.
    """
    # ── already done ──────────────────────────────────────────────────────────
    if persona.status == PersonaStatus.PUBLISHED_PRIVATE:
        _logger.info("persona %s already privately published, skipping", persona.id)
        return persona

    if persona.status != PersonaStatus.GENERATED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Persona must be GENERATED before publishing (current: {persona.status})",
        )

    # ── payment gate ──────────────────────────────────────────────────────────
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

    # ── github connection gate ────────────────────────────────────────────────
    if not user.github_connected or not user.github_access_token_encrypted:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "github_not_connected",
                "message": "Connect your GitHub account before private publishing.",
            },
        )

    token = decrypt(user.github_access_token_encrypted)
    username = user.github_username or await _get_github_username(token)

    # ── create repo in user's account ─────────────────────────────────────────
    slug = slugify(persona.name)
    repo = await create_or_get_user_repo(
        slug=slug,
        description=(persona.description_summary or f"Persona: {persona.name}")[:255],
        token=token,
        private=True,
    )

    # ── push files ────────────────────────────────────────────────────────────
    files = {
        "README.md": persona.readme_md,
        "identity.md": persona.identity_md,
        "soul.md": persona.soul_md,
        "dna.md": persona.dna_md,
        "overview.md": persona.overview_md,
        "heartbeat.md": persona.heartbeat_md,
    }
    for filename, content in files.items():
        await upsert_user_file(
            username, slug, filename, content, f"chore: publish {filename}", token
        )

    skills = await _get_persona_skills(persona.id, db)
    for skill in skills:
        if not is_safe_skill_slug(skill.slug):
            _logger.warning("skipping unsafe skill slug %r in private publish", skill.slug)
            continue
        safe_files = safe_skill_files(skill.files)
        if safe_files:
            for entry in safe_files:
                await upsert_user_file(
                    username,
                    slug,
                    f"skills/{skill.slug}/{entry['path']}",
                    entry["content"],
                    f"chore: add skill {skill.slug}/{entry['path']}",
                    token,
                )
        elif skill.content:
            skill_md = build_skill_md(
                skill.slug,
                {
                    "displayName": skill.name,
                    "summary": skill.description,
                    "tags": skill.tags or [],
                    "ownerHandle": skill.source_author or "",
                    "url": skill.source_url or "",
                },
                source_url=skill.source_url or "",
            )
            await upsert_user_file(
                username,
                slug,
                f"skills/{skill.slug.split('/')[-1]}.md",
                skill_md,
                f"chore: add skill {skill.slug}",
                token,
            )
        else:
            _logger.warning("skipping skill %s: both files and content empty", skill.slug)

    # ── persist ───────────────────────────────────────────────────────────────
    persona.status = PersonaStatus.PUBLISHED_PRIVATE
    persona.github_repo_url = repo.get("html_url")
    persona.github_clone_url = repo.get("clone_url")
    persona.github_zip_url = (
        f"{repo.get('html_url', '')}/archive/refs/heads/{repo.get('default_branch', 'main')}.zip"
    )
    await db.commit()
    _logger.info(
        "event=persona.private_publish.success persona_id=%s repo=%s user_id=%s",
        persona.id,
        persona.github_repo_url,
        user.id,
    )
    return persona
