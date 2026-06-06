import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _base() -> str:
    return settings.OPENCLAW_API_BASE.rstrip("/")


async def fetch_skill(slug: str) -> dict[str, Any] | None:
    """GET /api/v1/skills/{slug}

    Returns a flattened dict merging skill + latestVersion + owner +
    moderation, or None if not found / error.
    """
    if not slug or not slug.strip():
        return None
    url = f"{_base()}/skills/{slug}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return None
            return _flatten(payload)
    except httpx.HTTPError as exc:
        logger.warning("ClawHub fetch_skill failed for %s: %s", slug, exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error in fetch_skill for %s: %s", slug, exc)
        return None


async def search_skills(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """GET /api/v1/search?q={query}

    Returns a list of result dicts. Each result contains:
      slug, displayName, summary, version, ownerHandle, owner, score
    """
    if limit < 1:
        limit = 5
    if limit > 100:
        limit = 100
    url = f"{_base()}/search"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                url,
                params={"q": query, "limit": limit, "nonSuspiciousOnly": "true"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return []
            results = payload.get("results", [])
            return [r for r in results if isinstance(r, dict)]
    except httpx.HTTPError as exc:
        logger.warning("ClawHub search failed for %r: %s", query, exc)
        return []
    except Exception as exc:
        logger.warning("Unexpected error in search_skills for %r: %s", query, exc)
        return []


def passes_moderation(detail: dict[str, Any]) -> bool:
    """Return False if the skill is flagged suspicious, malware-blocked, or non-clean."""
    moderation = detail.get("moderation") or {}
    if moderation.get("isSuspicious"):
        return False
    if moderation.get("isMalwareBlocked"):
        return False
    verdict = moderation.get("verdict", "clean")
    if verdict and verdict != "clean":
        return False
    return True


def _flatten(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge nested ClawHub skill response into a flat dict."""
    skill = payload.get("skill") or {}
    latest = payload.get("latestVersion") or {}
    owner = payload.get("owner") or {}
    moderation = payload.get("moderation") or {}

    return {
        **skill,
        "latestVersion": latest.get("version", ""),
        "changelog": latest.get("changelog", ""),
        "owner": owner,
        "ownerHandle": owner.get("handle", ""),
        "moderation": moderation,
        "displayName": skill.get("displayName", ""),
        "summary": skill.get("summary", ""),
        "tags": skill.get("tags") or [],
        "stats": skill.get("stats") or {},
    }
