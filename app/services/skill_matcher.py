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

    normalized_slugs = _normalize_slugs(suggested_slugs, limit=6)

    if not normalized_slugs:
        return await _get_seeded_skills(
            db,
            category=category,
            limit=2,
            exclude_slugs=set(),
        )

    local_skills = await _get_local_skills_by_slugs(normalized_slugs, db)

    resolved: list[Skill] = []
    seen_slugs: set[str] = set()

    for slug in normalized_slugs:
        skill = local_skills.get(slug)

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


async def _fetch_openclaw_skill(
    query: str,
    category: str,
    db: AsyncSession,
) -> Skill | None:
    """Search OpenClaw for a skill, fetch its full content."""
    try:
        results = await search_openclaw_skills(query, limit=1)
    except Exception as exc:
        logger.warning("OpenClaw search failed for %s: %s", query, exc)
        return None

    if not results:
        return None

    item = results[0]
    skill_id = str(item.get("slug") or item.get("name") or item.get("id") or "").strip()

    if not skill_id:
        return None

    try:
        detail = await fetch_openclaw_skill(skill_id)
    except Exception as exc:
        logger.warning("OpenClaw detail fetch failed for skill %s: %s", skill_id, exc)
        detail = None

    return await _upsert_openclaw_skill(
        item=item,
        detail=detail or item,
        category=category,
        db=db,
    )


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

    skill_ref = (
        detail.get("id")
        or detail.get("slug")
        or item.get("id")
        or item.get("slug")
        or detail.get("name")
        or item.get("name")
        or ""
    )
    try:
        content = await fetch_openclaw_skill_markdown(skill_ref) if skill_ref else ""
    except Exception as exc:
        logger.warning("OpenClaw markdown fetch failed for skill %s: %s", skill_ref, exc)
        content = ""

    values = {
        "name": (
            detail.get("displayName") or item.get("displayName") or slug.replace("-", " ").title()
        ),
        "description": (
            detail.get("summary")
            or detail.get("description")
            or item.get("summary")
            or item.get("description")
            or ""
        ),
        "content": content,
        "category": detail.get("category") or item.get("category") or category,
        "tags": detail.get("tags") or item.get("tags") or [],
        "source_registry": SkillSourceRegistry.OPENCLAW,
        "source_url": (
            detail.get("url")
            or item.get("url")
            or f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_ref}/file?path=skill.md"
        ),
        "source_author": (
            (detail.get("owner") or {}).get("displayName")
            or (item.get("owner") or {}).get("displayName")
            or detail.get("handle")
            or item.get("handle")
        ),
        "install_count": _safe_int(
            (detail.get("stats") or {}).get("downloads")
            or (item.get("stats") or {}).get("downloads")
            or detail.get("install_count")
            or item.get("install_count")
            or 0
        ),
        "is_active": True,
    }

    result = await db.execute(select(Skill).where(Skill.slug == slug))
    skill = result.scalar_one_or_none()

    if skill is not None:
        for field, value in values.items():
            setattr(skill, field, value)

        await db.flush()
        return skill

    skill = Skill(slug=slug, **values)

    try:
        async with db.begin_nested():
            db.add(skill)
            await db.flush()

        return skill

    except IntegrityError:
        # Another transaction inserted the same slug concurrently.
        result = await db.execute(select(Skill).where(Skill.slug == slug))
        existing = result.scalar_one_or_none()

        if existing is None:
            raise

        for field, value in values.items():
            setattr(existing, field, value)

        await db.flush()
        return existing


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
    if isinstance(value, str):
        value = value.strip().replace(",", "")
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_slugs(raw_slugs: list[str], limit: int = 6) -> list[str]:
    """Normalize and deduplicate suggested slugs while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_slug in raw_slugs:
        slug = raw_slug.strip().lower()

        if not slug or slug in seen:
            continue

        normalized.append(slug)
        seen.add(slug)

        if len(normalized) >= limit:
            break

    return normalized


async def _get_local_skills_by_slugs(
    slugs: list[str],
    db: AsyncSession,
) -> dict[str, Skill]:
    """Fetch all active local skills for given slugs in one query."""
    if not slugs:
        return {}

    result = await db.execute(
        select(Skill).where(
            Skill.slug.in_(slugs),
            Skill.is_active.is_(True),
        )
    )

    return {skill.slug: skill for skill in result.scalars().all()}
