import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaStatus
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.services.github_service import create_or_get_repo, upsert_file
from app.utils.slugify import slugify

logger = logging.getLogger(__name__)


PERSONA_FILES: list[tuple[str, str]] = [
    ("readme_md", "README.md"),
    ("identity_md", "identity.md"),
    ("soul_md", "soul.md"),
    ("dna_md", "dna.md"),
    ("overview_md", "overview.md"),
    ("heartbeat_md", "heartbeat.md"),
]


async def publish_persona(persona: Persona, db: AsyncSession) -> Persona:
    """
    Publish a persona to GitHub and mark it PUBLISHED.
    """
    if persona.status == PersonaStatus.PUBLISHED:
        logger.info("persona %s already published, skipping", persona.id)
        return persona

    if persona.status != PersonaStatus.GENERATED:
        raise HTTPException(
            status_code=400,
            detail=f"persona {persona.id} must be GENERATED before publishing "
            f"(current status: {persona.status})",
        )
    slug = slugify(persona.name)

    repo = await create_or_get_repo(
        slug=slug,
        description=(persona.description_summary or f"Persona: {persona.name}")[:255],
    )

    skills = await _get_persona_skills(persona.id, db)

    files = {
        "README.md": persona.readme_md,
        "identity.md": persona.identity_md,
        "soul.md": persona.soul_md,
        "dna.md": persona.dna_md,
        "overview.md": persona.overview_md,
        "heartbeat.md": persona.heartbeat_md,
    }

    for filename, content in files.items():
        await upsert_file(
            slug=slug,
            path=filename,
            content=content,
            message=f"chore: publish {filename}",
        )

    # Persona markdown files → repo root
    for skill in skills:
        await upsert_file(
            slug=slug,
            path=f"skills/{skill.slug}.md",
            content=skill.content,
            message=f"chore: add skill {skill.slug}",
        )

    persona.status = PersonaStatus.PUBLISHED
    persona.github_repo_url = repo.get("html_url")
    persona.github_clone_url = repo.get("clone_url")
    persona.github_zip_url = (
        f"{repo.get('html_url', '')}/archive/refs/heads/{repo.get('default_branch', 'main')}.zip"
    )
    await db.commit()

    logger.info(
        "persona %s published to %s with %d skill(s)",
        persona.id,
        persona.github_repo_url,
        len(skills),
    )
    return persona


async def _get_persona_skills(persona_id, db: AsyncSession) -> list[Skill]:
    result = await db.execute(
        select(Skill)
        .join(PersonaSkill, PersonaSkill.skill_id == Skill.id)
        .where(PersonaSkill.persona_id == persona_id)
    )
    return list(result.scalars().all())
