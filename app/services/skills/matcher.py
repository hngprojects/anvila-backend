import logging
import re
from typing import Any

from sqlalchemy import ARRAY, String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SkillSourceRegistry
from app.models.skill import Skill
from app.services.skills.clawhub import fetch_skill, passes_moderation, search_skills
from app.services.skills.fallbacks import CATEGORY_FALLBACKS, GENERIC_FALLBACKS
from app.services.skills.prompt_builder import build_install_prompt, build_skill_md

logger = logging.getLogger(__name__)

_MIN_SKILLS = 2
_MAX_SKILLS = 6
_MIN_KEYWORD_LENGTH = 3

SKILLS_REPO = "anvila-skills"


async def match_skills(
    suggested_slugs: list[str],
    category: str,
    db: AsyncSession,
) -> list[Skill]:
    """
    Resolve suggested slugs into 2–6 Skill ORM objects.

    Each returned skill is stored in the DB and pushed to the org GitHub repo.
    Skill.content always contains the current install prompt.
    """
    normalized = _normalize(suggested_slugs, limit=_MAX_SKILLS)
    resolved: list[Skill] = []
    seen: set[str] = set()

    for slug in normalized:
        if len(resolved) >= _MAX_SKILLS:
            break
        skill = await _resolve(slug, category, db)
        if skill and skill.slug not in seen:
            resolved.append(skill)
            seen.add(skill.slug)

    if len(resolved) < _MIN_SKILLS:
        fallback_slugs = CATEGORY_FALLBACKS.get(category, []) + GENERIC_FALLBACKS
        for slug in fallback_slugs:
            if len(resolved) >= _MIN_SKILLS:
                break
            if slug in seen:
                continue
            skill = await _resolve(slug, category, db)
            if skill and skill.slug not in seen:
                resolved.append(skill)
                seen.add(skill.slug)

    return resolved


def is_safe_skill_slug(slug: str) -> bool:
    if not slug or len(slug) > 220:
        return False
    if ".." in slug or slug.startswith("/") or slug.startswith("\\"):
        return False
    parts = slug.split("/")
    if len(parts) > 2:
        return False
    safe = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$")
    return all(safe.match(p) for p in parts if p)


async def _resolve(
    slug: str,
    category: str,
    db: AsyncSession,
) -> Skill | None:
    """Try all four resolution steps for a single slug."""

    skill = await _db_exact(slug, db)
    if skill:
        logger.debug("local exact hit: %s", slug)
        return await _refresh(skill, db)

    skill = await _db_fuzzy(slug, db)
    if skill:
        logger.debug("local fuzzy hit: %s → %s", slug, skill.slug)
        return await _refresh(skill, db)

    detail = await fetch_skill(slug)
    if detail and passes_moderation(detail):
        logger.debug("clawhub exact hit: %s", slug)
        return await _build_and_save(slug, detail, category, db)

    skill = await _clawhub_fuzzy(slug, category, db)
    if skill:
        logger.debug("clawhub fuzzy hit: %s", slug)
        return skill

    logger.debug("no match found for slug: %s", slug)
    return None


async def _db_exact(slug: str, db: AsyncSession) -> Skill | None:
    result = await db.execute(select(Skill).where(Skill.slug == slug, Skill.is_active.is_(True)))
    return result.scalar_one_or_none()


async def _db_fuzzy(slug: str, db: AsyncSession) -> Skill | None:
    keywords = _keywords(slug)
    if not keywords:
        return None

    name_filters = [func.lower(Skill.name).contains(kw) for kw in keywords]

    tag_filter = Skill.tags.op("&&")(cast(keywords, ARRAY(String)))

    result = await db.execute(
        select(Skill).where(
            Skill.is_active.is_(True),
            or_(*name_filters, tag_filter),
        )
    )
    candidates = result.scalars().all()

    for skill in candidates:
        name_words = set(skill.name.lower().split())
        tag_words = {t.lower() for t in (skill.tags or [])}
        combined = name_words | tag_words

        if all(kw in combined for kw in keywords):
            return skill

    return None


# async def _db_fuzzy(slug: str, db: AsyncSession) -> Skill | None:
#     """Match keywords from slug against Skill.name and Skill.tags in local DB."""
#     keywords = _keywords(slug)
#     if not keywords:
#         return None
#
#     result = await db.execute(select(Skill).where(Skill.is_active.is_(True)))
#     all_skills = result.scalars().all()
#
#     for skill in all_skills:
#         name_words = set(skill.name.lower().split())
#         tag_words = {t.lower() for t in (skill.tags or [])}
#         combined = name_words | tag_words
#
#         if all(kw in combined for kw in keywords):
#             return skill
#
#     return None


async def _clawhub_fuzzy(
    slug: str,
    category: str,
    db: AsyncSession,
) -> Skill | None:
    """Search ClawHub with keywords + category, fetch best result, build and save."""
    keywords = _keywords(slug)
    if not keywords:
        return None

    query = " ".join(keywords) + " " + category
    results = await search_skills(query)

    if not results:
        results = await search_skills(" ".join(keywords))

    if not results:
        return None

    best = results[0]
    result_slug = str(best.get("slug") or "").strip()
    if not result_slug:
        return None

    detail = await fetch_skill(result_slug)
    if not detail or not passes_moderation(detail):
        return None

    return await _build_and_save(result_slug, detail, category, db)


async def _build_and_save(
    slug: str,
    detail: dict[str, Any],
    category: str,
    db: AsyncSession,
) -> Skill | None:
    """Build install prompt, upsert Skill in DB, push SKILL.md to GitHub."""
    source_url = _source_url(slug, detail)
    install_prompt = build_install_prompt(slug, detail, source_url=source_url)
    skill_md_content = build_skill_md(slug, detail, source_url=source_url)

    values: dict[str, Any] = {
        "name": _name(slug, detail),
        "description": str(detail.get("summary") or detail.get("description") or "").strip(),
        "content": install_prompt,
        "category": category,
        "tags": detail.get("tags") or [],
        "source_registry": SkillSourceRegistry.OPENCLAW,
        "source_url": source_url,
        "source_author": (
            (detail.get("owner") or {}).get("displayName") or detail.get("ownerHandle") or ""
        ),
        "is_active": True,
    }

    skill = await _upsert(slug, values, db)
    if skill is None:
        return None

    await _push(slug, skill_md_content)
    return skill


async def _refresh(skill: Skill, db: AsyncSession) -> Skill:
    """Re-fetch ClawHub metadata and overwrite content with fresh install prompt."""
    detail = await fetch_skill(skill.slug)
    if not detail or not passes_moderation(detail):
        return skill

    source_url = _source_url(skill.slug, detail)
    skill.content = build_install_prompt(skill.slug, detail, source_url=source_url)
    skill.install_count = (skill.install_count or 0) + 1
    await db.flush()

    skill_md_content = build_skill_md(skill.slug, detail, source_url=source_url)
    await _push(skill.slug, skill_md_content)

    return skill


async def _upsert(
    slug: str,
    values: dict[str, Any],
    db: AsyncSession,
) -> Skill | None:
    """Insert or update Skill by slug, always incrementing install_count."""
    result = await db.execute(select(Skill).where(Skill.slug == slug))
    skill = result.scalar_one_or_none()

    if skill is not None:
        for field, value in values.items():
            setattr(skill, field, value)
        skill.install_count = (skill.install_count or 0) + 1
        await db.flush()
        return skill

    skill = Skill(slug=slug, install_count=1, **values)
    try:
        async with db.begin_nested():
            db.add(skill)
            await db.flush()
        return skill
    except IntegrityError:
        result = await db.execute(select(Skill).where(Skill.slug == slug))
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        for field, value in values.items():
            setattr(existing, field, value)
        existing.install_count = (existing.install_count or 0) + 1
        await db.flush()
        return existing


async def _push(slug: str, skill_md_content: str) -> None:
    """Push <slug>/SKILL.md to the org skills repo. Best-effort — never raises."""
    try:
        from app.services.github_service import create_or_get_repo, upsert_file

        path = slug.split("/")[-1]
        if not is_safe_skill_slug(path):
            logger.warning("skipping GitHub push — unsafe slug: %r", path)
            return

        await create_or_get_repo(
            slug=SKILLS_REPO,
            description="Shared skill library",
        )
        await upsert_file(
            slug=SKILLS_REPO,
            path=f"{path}.md",
            content=skill_md_content,
            message=f"chore: upsert skill {path}.md",
        )
        logger.info("pushed %s.md to org repo", path)
    except Exception:
        logger.exception("GitHub push failed for skill %s — continuing", slug)


def _keywords(slug: str) -> list[str]:
    """Extract meaningful keywords from a slug."""
    leaf = slug.split("/")[-1]
    return [
        w.lower()
        for w in leaf.replace("-", " ").replace("_", " ").split()
        if len(w) >= _MIN_KEYWORD_LENGTH
    ]


def _name(slug: str, metadata: dict[str, Any]) -> str:
    name = metadata.get("displayName") or metadata.get("name") or ""
    return str(name).strip() or slug.split("/")[-1].replace("-", " ").title()


def _source_url(slug: str, detail: dict[str, Any]) -> str:
    url = detail.get("url") or detail.get("skillPage") or ""
    if url:
        return str(url).strip()
    owner_handle = (detail.get("owner") or {}).get("handle") or detail.get("ownerHandle") or ""
    if owner_handle:
        return f"https://clawhub.ai/{owner_handle}/{slug.split('/')[-1]}"
    return f"https://clawhub.ai/{slug.strip('/')}"


def _normalize(raw: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for slug in raw:
        s = slug.strip().lower()
        if s and s not in seen:
            result.append(s)
            seen.add(s)
        if len(result) >= limit:
            break
    return result
