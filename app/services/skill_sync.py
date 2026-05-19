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


async def sync_skills_from_registry(category: str | None = None, limit: int | None = None) -> dict:
    """Fetch OpenClaw skills and upsert them into the local skills table."""
    try:
        skills_data = await list_openclaw_skills(category=category, limit=limit)

    except Exception as exc:
        logger.warning("OpenClaw sync failed: %s", exc)
        return {"synced": 0, "updated": 0, "added": 0}

    added = 0
    updated = 0

    async with AsyncSessionLocal() as db:
        for item in skills_data:
            slug = _make_slug(item)

            if not slug:
                continue

            content = await fetch_openclaw_skill_markdown(item.get("id") or item.get("slug") or "")

            result = await db.execute(select(Skill).where(Skill.slug == slug))
            skill = result.scalar_one_or_none()

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
                    source_url=f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_ref}/file?path=skill.md",
                    source_author=(
                        (item.get("owner") or {}).get("displayName") or item.get("handle")
                    ),
                    install_count=int(
                        (item.get("stats") or {}).get("downloads") or item.get("install_count") or 0
                    ),
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
                skill.source_url = (
                    f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_ref}/file?path=skill.md"
                    or skill.source_url
                )
                skill.source_author = (
                    (item.get("owner") or {}).get("displayName")
                    or item.get("handle")
                    or skill.source_author
                )
                skill.install_count = int(
                    (item.get("stats") or {}).get("downloads")
                    or item.get("install_count")
                    or skill.install_count
                    or 0
                )
                skill.is_active = True
                updated += 1

        await db.commit()

    return {
        "synced": added + updated,
        "updated": updated,
        "added": added,
    }


def _make_slug(item: dict[str, Any]) -> str:
    """Build a stable lowercase slug from an OpenClaw skill payload."""
    raw = item.get("slug") or item.get("name") or item.get("id") or ""

    return str(raw).strip().lower().replace(" ", "-")
