import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.enums import SkillSourceRegistry
from app.models.skill import Skill
from app.services.openclaw_client import (
    fetch_openclaw_skill_markdown,
    list_openclaw_skills,
)

logger = logging.getLogger(__name__)
OPENCLAW_FETCH_CONCURRENCY = 10


async def sync_skills_from_registry(category: str | None = None, limit=50) -> dict:
    """Fetch OpenClaw skills and upsert them into the local skills table."""
    try:
        skills_data = await list_openclaw_skills(category=category, limit=limit)

    except Exception as exc:
        logger.warning("OpenClaw sync failed: %s", exc)
        return {"synced": 0, "updated": 0, "added": 0}

    items_with_content = await _fetch_all_skill_markdowns(skills_data)

    added = 0
    updated = 0

    async with AsyncSessionLocal() as db:
        slugs = [_make_slug(item) for item in skills_data if _make_slug(item)]

        result = await db.execute(select(Skill).where(Skill.slug.in_(slugs)))
        existing_by_slug = {skill.slug: skill for skill in result.scalars().all()}

        for item, content in items_with_content:
            slug = _make_slug(item)

            if not slug:
                continue

            skill = existing_by_slug.get(slug)
            skill_ref = _skill_ref(item)

            if skill is None:
                skill_ref = item.get("id") or item.get("slug") or ""
                skill = Skill(
                    slug=slug,
                    name=(item.get("displayName") or item.get("name") or slug),
                    description=(item.get("summary") or item.get("description") or ""),
                    content=content,
                    category=item.get("category"),
                    tags=item.get("tags") or [],
                    source_registry=SkillSourceRegistry.OPENCLAW,
                    source_url=_source_url(skill_ref),
                    source_author=_source_author(item),
                    install_count=_install_count(item),
                    is_active=True,
                )
                db.add(skill)
                added += 1

            else:
                skill.name = item.get("displayName") or item.get("name") or skill.name
                skill.description = (
                    item.get("summary") or item.get("description") or skill.description
                )
                skill.content = content or skill.content
                skill.category = item.get("category") or skill.category
                skill.tags = item.get("tags") or skill.tags
                skill.source_registry = SkillSourceRegistry.OPENCLAW
                skill_ref = item.get("id") or item.get("slug") or ""
                skill.source_url = _source_url(skill_ref) or skill.source_url
                skill.source_author = _source_author(item) or skill.source_author
                skill.install_count = _install_count(item, fallback=skill.install_count)
                skill.is_active = True
                updated += 1

        await db.commit()

    return {
        "synced": added + updated,
        "updated": updated,
        "added": added,
    }


async def _fetch_all_skill_markdowns(
    skills_data: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], str]]:
    semaphore = asyncio.Semaphore(OPENCLAW_FETCH_CONCURRENCY)

    async def fetch_one(item: dict[str, Any]) -> tuple[dict[str, Any], str]:
        async with semaphore:
            skill_ref = _skill_ref(item)

            if not skill_ref:
                return item, ""

            try:
                content = await fetch_openclaw_skill_markdown(skill_ref)

                return item, content or ""

            except Exception as exc:
                logger.warning(
                    "Failed fetching OpenClaw markdown: skill_ref=%s exc=%s",
                    skill_ref,
                    exc,
                )
                return item, ""

    return await asyncio.gather(*(fetch_one(item) for item in skills_data))


def _make_slug(item: dict[str, Any]) -> str:
    """Build a stable lowercase slug from an OpenClaw skill payload."""
    raw = item.get("slug") or item.get("name") or item.get("id") or ""

    return str(raw).strip().lower().replace(" ", "-")


def _skill_ref(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("slug") or "").strip()


def _source_url(skill_ref: str) -> str:
    if not skill_ref:
        return ""

    return f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_ref}/file?path=skill.md"


def _source_author(item: dict[str, Any]) -> str | None:
    owner = item.get("owner") or {}
    return owner.get("displayName") or item.get("handle")


def _install_count(item: dict[str, Any], fallback: int | None = 0) -> int:
    return _safe_int(
        (item.get("stats") or {}).get("downloads") or item.get("install_count") or fallback or 0
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
