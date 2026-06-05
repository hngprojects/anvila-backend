import logging
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaStatus
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.services.github_service import create_or_get_repo, upsert_file
from app.services.skills.prompt_builder import build_skill_md
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


def safe_skill_files(files: list[dict] | None) -> list[dict[str, str]]:
    """Filter skill file entries to paths that cannot escape their skill folder.

    Drops entries where the path is:
      - not a string, empty, or whitespace-only
      - absolute (starts with "/")
      - contains a backslash
      - contains a ".." segment after POSIX normalisation

    Also drops entries that aren't dicts, or whose "content" isn't a string.
    Returns a new list; does not mutate the input.
    """
    if not files:
        return []

    safe: list[dict[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        content = entry.get("content")
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(content, str):
            continue
        if path.startswith("/") or "\\" in path:
            continue
        parts = PurePosixPath(path).parts
        if ".." in parts:
            continue
        safe.append({"path": path, "content": content})
    return safe


def is_safe_skill_slug(slug: str | None) -> bool:
    """Return True if the slug is safe to use as a path component.

    Rejects:
      - non-strings or empty/whitespace-only strings
      - any string containing "/", "\\", or ".."
      - strings starting with "." (hidden-file convention; also
        catches the degenerate case where the slug IS just "..")
    """
    if not isinstance(slug, str) or not slug.strip():
        return False
    if "/" in slug or "\\" in slug or ".." in slug:
        return False
    if slug.startswith("."):
        return False
    return True


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

    for skill in skills:
        if not is_safe_skill_slug(skill.slug):
            logger.warning(
                "skipping skill id=%s with unsafe slug %r in publish: refusing to write to GitHub",
                skill.id,
                skill.slug,
            )
            continue

        safe_files = safe_skill_files(skill.files)
        if safe_files:
            for entry in safe_files:
                await upsert_file(
                    slug=slug,
                    path=f"skills/{skill.slug}/{entry['path']}",
                    content=entry["content"],
                    message=f"chore: add skill {skill.slug}/{entry['path']}",
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
            await upsert_file(
                slug=slug,
                path=f"skills/{skill.slug.split('/')[-1]}.md",
                content=skill_md,
                message=f"chore: add skill {skill.slug}",
            )
        else:
            logger.warning(
                "skipping skill %s in publish: both files and content empty",
                skill.slug,
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
