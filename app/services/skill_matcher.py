import logging
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import SkillSourceRegistry
from app.models.skill import Skill
from app.services.openclaw_client import (
    download_openclaw_skill_zip,
    fetch_openclaw_skill,
    fetch_openclaw_skill_markdown,
    search_openclaw_skills,
)
from app.services.publish_service import create_or_get_repo, safe_skill_files, upsert_file

SKILLS_REPO = "skills"

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

    local_pool = await _get_local_skill_pool(category, db)
    local_by_slug = {s.slug: s for s in local_pool}

    resolved: list[Skill] = []
    seen_slugs: set[str] = set()

    for slug in normalized_slugs:
        skill = local_by_slug.get(slug) or _find_similar(slug, local_pool, exclude_slugs=seen_slugs)

        if skill is not None:
            logger.debug("reusing local skill %s for suggestion %s", skill.slug, slug)
        else:
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


async def push_skill_to_org_repo(skill: Skill) -> None:
    """
    Push a skill to the shared org skills repo as a folder under
    <slug>/, falling back to <slug>.md for legacy single-file skills.
    """
    try:
        await create_or_get_repo(
            slug=SKILLS_REPO,
            description="Shared skill library",
        )

        safe_files = safe_skill_files(skill.files)
        if safe_files:
            for entry in safe_files:
                await upsert_file(
                    slug=SKILLS_REPO,
                    path=f"{skill.slug}/{entry['path']}",
                    content=entry["content"],
                    message=f"chore: upsert skill {skill.slug}/{entry['path']}",
                )
        elif skill.content:
            await upsert_file(
                slug=SKILLS_REPO,
                path=f"{skill.slug}.md",
                content=skill.content,
                message=f"chore: upsert skill {skill.slug}",
            )
        else:
            logger.warning(
                "skipping push of skill %s to org repo: both files and content empty",
                skill.slug,
            )
            return

        logger.info("pushed skill %s to org skills repo", skill.slug)
    except Exception:
        logger.exception(
            "GitHub push failed for skill %s — saved locally, continuing",
            skill.slug,
        )


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

    skill = await _upsert_openclaw_skill(
        item=item,
        detail=detail or item,
        category=category,
        db=db,
    )

    if skill is not None:
        await push_skill_to_org_repo(skill)
    return skill


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
    files = await download_openclaw_skill_zip(slug)
    content = _extract_skill_md(files)

    if not content:
        try:
            content = await fetch_openclaw_skill_markdown(skill_ref) if skill_ref else ""
        except Exception as exc:
            logger.warning(
                "OpenClaw markdown fallback fetch failed for %s: %s",
                skill_ref,
                exc,
            )
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
        "files": files,
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
        _safe_update_skill(skill, values)
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

        _safe_update_skill(existing, values)
        await db.flush()
        return existing


def _safe_update_skill(skill: Skill, values: dict[str, Any]) -> None:
    """Update fields without clobbering cached content on empty fetches."""
    for field, value in values.items():
        if field in ("content", "files") and not value and getattr(skill, field):
            continue
        setattr(skill, field, value)


def _extract_skill_md(files: list[dict[str, str]]) -> str:
    """Return the content of SKILL.md from a skill file list, or empty.

    Matches the basename to avoid over-matching files like my-skill.md or
    not-skill.md.
    """
    for entry in files:
        if PurePosixPath(entry["path"]).name.lower() == "skill.md":
            return entry["content"]

    return ""


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


def _find_similar(
    slug: str,
    pool: list[Skill],
    exclude_slugs: set[str],
) -> Skill | None:
    """
    Find a skill in `pool` that is similar to `slug` without a DB query.
    """
    keywords = [w for w in slug.split("-") if len(w) > 2]

    if len(keywords) < 2:
        return None

    for skill in pool:
        if skill.slug in exclude_slugs:
            continue

        name_words = set(skill.name.lower().split())
        tags = {t.lower() for t in (skill.tags or [])}

        name_match = all(kw in name_words for kw in keywords)
        tag_match = any(kw in tags for kw in keywords)

        if name_match or tag_match:
            return skill

    return None


async def _get_local_skill_pool(
    category: str,
    db: AsyncSession,
) -> list[Skill]:
    """
    Fetch all active local skills for a category in one query.

    Used to power both exact-slug lookup and similarity matching without
    issuing per-slug queries. Also includes skills with no category set
    (source_registry=ANVILA seeds often omit it) so they're available as
    fallback candidates.
    """
    result = await db.execute(
        select(Skill).where(
            Skill.is_active.is_(True),
            or_(Skill.category == category, Skill.category.is_(None)),
        )
    )
    return list(result.scalars().all())
