import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaStatus
from app.models.persona import Persona, PersonaVisibility
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.services.publish_service import safe_skill_files
from app.services.skills import is_safe_skill_slug
from app.services.skills.prompt_builder import build_skill_md

logger = logging.getLogger(__name__)

UpsertFn = Callable[[str, str | None, str], Awaitable[None]]


async def push_files(persona: Persona, upsert: UpsertFn) -> None:
    """Push the core persona markdown files."""
    files = {
        "README.md": persona.readme_md,
        "identity.md": persona.identity_md,
        "soul.md": persona.soul_md,
        "dna.md": persona.dna_md,
        "overview.md": persona.overview_md,
        "heartbeat.md": persona.heartbeat_md,
    }
    for filename, content in files.items():
        await upsert(filename, content, f"chore: publish {filename}")


async def push_skills(skills: list[Any], upsert: UpsertFn) -> None:
    """Push all skills with safety checks."""
    for skill in skills:
        if not is_safe_skill_slug(skill.slug):
            logger.warning(
                "skipping skill id=%s with unsafe slug %r in publish",
                skill.id,
                skill.slug,
            )
            continue

        safe_files = safe_skill_files(skill.files)
        if safe_files:
            for entry in safe_files:
                await upsert(
                    f"skills/{skill.slug}/{entry['path']}",
                    entry["content"],
                    f"chore: add skill {skill.slug}/{entry['path']}",
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
            await upsert(
                f"skills/{skill.slug.split('/')[-1]}.md",
                skill_md,
                f"chore: add skill {skill.slug}",
            )
        else:
            logger.warning("skipping skill %s in publish: both files and content empty", skill.slug)


async def persist_persona(
    persona: Persona,
    repo: dict,
    visibility: PersonaVisibility,
    db: AsyncSession,
) -> None:
    """Set GitHub URLs, status, visibility and commit."""
    persona.status = PersonaStatus.PUBLISHED
    persona.visibility = visibility
    persona.github_repo_url = repo.get("html_url")
    persona.github_clone_url = repo.get("clone_url")
    persona.github_zip_url = (
        f"{repo.get('html_url', '')}/archive/refs/heads/{repo.get('default_branch', 'main')}.zip"
    )
    await db.commit()


async def get_persona_skills(persona_id, db: AsyncSession) -> list[Skill]:
    result = await db.execute(
        select(Skill)
        .join(PersonaSkill, PersonaSkill.skill_id == Skill.id)
        .where(PersonaSkill.persona_id == persona_id)
    )
    return list(result.scalars().all())
