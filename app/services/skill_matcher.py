import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import SkillSourceRegistry
from app.models.skill import Skill
from app.services.openclaw_client import (
    fetch_openclaw_skill,
    fetch_openclaw_skill_markdown,
    search_openclaw_skills,
)

logger = logging.getLogger(__name__)


async def match_skills(
    suggested_slugs: list[str],
    category: str,
    db: AsyncSession,
) -> list[Skill]:
    """Resolve suggested skill slugs into 2-6 Skill ORM objects."""
    resolved: list[Skill] = []
    seen_slugs: set[str] = set()

    for raw_slug in suggested_slugs[:6]:
        slug = raw_slug.strip().lower()

        if not slug or slug in seen_slugs:
            continue

        skill = await _get_local_skill_by_slug(slug, db)

        if skill is None:
            skill = await _fetch_openclaw_skill(slug, category, db)

        if skill and skill.slug not in seen_slugs:
            resolved.append(skill)
            seen_slugs.add(skill.slug)

    if len(resolved) < 2:
        padding = await _get_seeded_skills(
            db,
            category=category,
            limit=2 - len(resolved),
            exclude_slugs=seen_slugs,
        )
        resolved.extend(padding)

    return resolved[:6]


async def _get_local_skill_by_slug(slug: str, db: AsyncSession) -> Skill | None:
    """Return an active locally skill by slug."""
    result = await db.execute(
        select(Skill).where(
            Skill.slug == slug,
            Skill.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _fetch_openclaw_skill(
    query: str,
    category: str,
    db: AsyncSession,
) -> Skill | None:
    """Search OpenClaw for a skill, fetch its full content."""
    results = await search_openclaw_skills(query, limit=1)

    if not results:
        return None

    item = results[0]
    skill_id = str(item.get("slug") or item.get("name") or item.get("id") or "").strip()

    if not skill_id:
        return None

    detail = await fetch_openclaw_skill(skill_id)

    if detail is None:
        detail = item

    return await _upsert_openclaw_skill(item, detail, category, db)


async def _upsert_openclaw_skill(
    item: dict[str, Any],
    detail: dict[str, Any],
    category: str,
    db: AsyncSession,
) -> Skill | None:
    """Create or update an OpenClaw skill using slug as the unique key."""
    slug = (
        str(
            detail.get("slug")
            or item.get("slug")
            or detail.get("displayName")
            or item.get("displayName")
            or ""
        )
        .strip()
        .lower()
        .replace(" ", "-")
    )

    if not slug:
        return None

    content = await fetch_openclaw_skill_markdown(item.get("id") or item.get("slug") or "")

    result = await db.execute(select(Skill).where(Skill.slug == slug))
    skill = result.scalar_one_or_none()

    if skill is None:
        skill_ref = item.get("id") or item.get("slug") or ""
        skill = Skill(
            slug=slug,
            name=detail.get("displayName")
            or item.get("displayName")
            or slug.replace("-", " ").title(),
            description=detail.get("summary")
            or detail.get("description")
            or item.get("summary")
            or item.get("description")
            or "",
            content=content,
            category=detail.get("category") or item.get("category") or category,
            tags=detail.get("tags") or item.get("tags") or [],
            source_registry=SkillSourceRegistry.OPENCLAW,
            source_url=detail.get("url")
            or item.get("url")
            or f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_ref}/file?path=skill.md",
            source_author=(
                (detail.get("owner") or {}).get("displayName")
                or (item.get("owner") or {}).get("displayName")
                or detail.get("handle")
                or item.get("handle")
            ),
            install_count=_safe_int(
                (detail.get("stats") or {}).get("downloads")
                or (item.get("stats") or {}).get("downloads")
                or detail.get("install_count")
                or item.get("install_count")
                or 0
            ),
            is_active=True,
        )
        db.add(skill)
    else:
        skill.name = detail.get("displayName") or item.get("displayName") or skill.name
        skill.description = (
            detail.get("summary")
            or detail.get("description")
            or item.get("summary")
            or item.get("description")
            or skill.description
        )
        skill.content = content or skill.content
        skill.category = detail.get("category") or item.get("category") or skill.category
        skill.tags = detail.get("tags") or item.get("tags") or skill.tags
        skill.source_registry = SkillSourceRegistry.OPENCLAW
        skill_ref = item.get("id") or item.get("slug") or ""
        skill.source_url = (
            detail.get("url")
            or item.get("url")
            or f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_ref}/file?path=skill.md"
            or skill.source_url
        )
        skill.source_author = (
            (detail.get("owner") or {}).get("displayName")
            or (item.get("owner") or {}).get("displayName")
            or detail.get("handle")
            or item.get("handle")
            or skill.source_author
        )
        skill.install_count = _safe_int(
            (detail.get("stats") or {}).get("downloads")
            or (item.get("stats") or {}).get("downloads")
            or detail.get("install_count")
            or item.get("install_count")
            or skill.install_count
            or 0
        )
        skill.is_active = True

    async with db.begin_nested():
        try:
            await db.flush()
        except IntegrityError:
            pass

    return skill


async def _get_seeded_skills(
    db: AsyncSession,
    *,
    category: str,
    limit: int,
    exclude_slugs: set[str],
) -> list[Skill]:
    """Return active Anvila fallback skills for the given category."""
    query = select(Skill).where(
        Skill.category == category,
        Skill.is_active.is_(True),
        Skill.source_registry == SkillSourceRegistry.ANVILA,
    )

    if exclude_slugs:
        query = query.where(Skill.slug.not_in(exclude_slugs))

    result = await db.execute(query.limit(limit))
    return list(result.scalars().all())


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
