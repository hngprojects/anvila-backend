import logging
from functools import partial

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona, PersonaStatus, PersonaVisibility
from app.services.publishing.github import create_org_repo, upsert_org_file
from app.services.publishing.utils import (
    get_persona_skills,
    persist_persona,
    push_files,
    push_skills,
)
from app.utils.slugify import slugify

logger = logging.getLogger(__name__)


async def publish_persona(persona: Persona, db: AsyncSession) -> Persona:
    """Publish a persona to the org GitHub account as a public repo."""
    if persona.status == PersonaStatus.PUBLISHED and persona.visibility == PersonaVisibility.PUBLIC:
        logger.info("persona %s already publicly published, skipping", persona.id)
        return persona

    if persona.status != PersonaStatus.GENERATED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Persona must be GENERATED before publishing (current: {persona.status})",
        )

    slug = slugify(persona.name)
    repo = await create_org_repo(
        slug=slug,
        description=(persona.description_summary or f"Persona: {persona.name}")[:255],
    )

    upsert = partial(upsert_org_file, slug)

    skills = await get_persona_skills(persona.id, db)
    await push_files(persona, upsert)
    await push_skills(skills, upsert)
    await persist_persona(persona, repo, PersonaVisibility.PUBLIC, db)

    logger.info(
        "event=persona.publish.public persona_id=%s repo=%s skills=%d",
        persona.id,
        persona.github_repo_url,
        len(skills),
    )
    return persona
