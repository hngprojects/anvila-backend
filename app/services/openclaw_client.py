import io
import json
import logging
import zipfile
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Defensive caps for zip extraction. Real skills today are well under 1 MiB
# total; anything over is more likely pathological than legitimate. Tunable
# here if real-world skills grow.
_MAX_SKILL_FILE_SIZE = 1 * 1024 * 1024  # 1 MiB per file
_MAX_SKILL_TOTAL_SIZE = 10 * 1024 * 1024  # 10 MiB cumulative


async def list_openclaw_skills(
    category: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """List recent OpenClaw/ClawHub skills with optional category filtering."""
    url = f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills"

    params: dict[str, Any] = {
        "limit": limit,
        "nonSuspiciousOnly": "true",
    }

    if category:
        params["category"] = category

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("OpenClaw skill list failed for category %s: %s", category, exc)
        return []

    return _extract_list(response.json())


async def search_openclaw_skills(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search OpenClaw/ClawHub skills by plain text query."""
    url = f"{settings.OPENCLAW_API_BASE.rstrip('/')}/search"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url,
                params={
                    "q": query,
                    "limit": limit,
                    "nonSuspiciousOnly": "true",
                },
            )
            response.raise_for_status()

    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("OpenClaw skill search failed for %s: %s", query, exc)
        return []

    return _extract_list(response.json())


async def fetch_openclaw_skill(skill_id: str) -> dict[str, Any] | None:
    """Fetch full OpenClaw/ClawHub skill details by skill id or slug."""
    url = f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_id}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()

    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("OpenClaw skill fetch failed for %s: %s", skill_id, exc)
        return None

    payload = response.json()

    if isinstance(payload, dict):
        return payload

    return None


async def fetch_openclaw_skill_markdown(skill_id: str) -> str:
    """Fetch the SKILL.md content of an OpenClaw/ClawHub skill."""
    url = f"{settings.OPENCLAW_API_BASE.rstrip('/')}/skills/{skill_id}/file?path=skill.md"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()

    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("OpenClaw skill markdown fetch failed for %s: %s", skill_id, exc)
        return ""

    return response.text


async def download_openclaw_skill_zip(slug: str) -> list[dict[str, str]]:
    """Download an OpenClaw/ClawHub skill zip and return its UTF-8 text files."""
    url = f"{settings.OPENCLAW_API_BASE.rstrip('/')}/download"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params={"slug": slug})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("OpenClaw zip download failed for %s: %s", slug, exc)
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            files: list[dict[str, str]] = []
            total_size = 0

            for info in zf.infolist():
                if info.is_dir():
                    continue

                if info.file_size > _MAX_SKILL_FILE_SIZE:
                    logger.warning(
                        "skipping oversized file %s (%d bytes) in skill %s",
                        info.filename,
                        info.file_size,
                        slug,
                    )
                    continue

                if total_size + info.file_size > _MAX_SKILL_TOTAL_SIZE:
                    logger.warning(
                        "skill %s exceeds cumulative size cap (%d MiB), truncating after %d files",
                        slug,
                        _MAX_SKILL_TOTAL_SIZE // (1024 * 1024),
                        len(files),
                    )
                    break

                total_size += info.file_size

                try:
                    raw = zf.read(info.filename)
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    logger.warning(
                        "skipping non-UTF-8 file %s in skill %s",
                        info.filename,
                        slug,
                    )
                    continue
                except zipfile.BadZipFile as exc:
                    logger.warning(
                        "bad zip entry %s in skill %s: %s",
                        info.filename,
                        slug,
                        exc,
                    )
                    continue

                files.append({"path": info.filename, "content": content})

            return files
    except zipfile.BadZipFile as exc:
        logger.warning("OpenClaw returned malformed zip for %s: %s", slug, exc)
        return []


def _extract_list(payload: Any) -> list[dict[str, Any]]:
    """Normalize OpenClaw list/search responses into a list of dicts."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("skills", "data", "results", "items"):
            value = payload.get(key)

            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []
