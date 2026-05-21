import base64

import httpx
from fastapi import HTTPException

from app.core.config import settings

GITHUB_API = "https://api.github.com"


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _b64(content: str | None) -> str:
    return base64.b64encode((content or "").encode()).decode()


async def create_or_get_repo(slug: str, description: str) -> dict:
    """Create a repo in the org — if it already exists, fetch and return it."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/orgs/{settings.GITHUB_ORG}/repos",
            headers=_gh_headers(),
            json={
                "name": slug,
                "description": description[:255],
                "private": False,
                "auto_init": False,
            },
        )

    if resp.status_code == 422:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{settings.GITHUB_ORG}/{slug}",
                headers=_gh_headers(),
            )

    if not resp.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub repo creation failed: {resp.text}",
        )

    return resp.json()


async def upsert_file(slug: str, path: str, content: str | None, message: str) -> None:
    """Push a single file — creates it if new, updates it if already exists."""
    if not content:
        return

    url = f"{GITHUB_API}/repos/{settings.GITHUB_ORG}/{slug}/contents/{path}"

    async with httpx.AsyncClient() as client:
        existing = await client.get(url, headers=_gh_headers())

    payload: dict = {
        "message": message,
        "content": _b64(content),
    }
    if existing.is_success:
        payload["sha"] = existing.json()["sha"]

    async with httpx.AsyncClient() as client:
        resp = await client.put(url, headers=_gh_headers(), json=payload)

    if not resp.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to write {path}: {resp.text}",
        )
