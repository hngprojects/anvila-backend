import base64
import logging

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

_logger = logging.getLogger(__name__)
GITHUB_API = "https://api.github.com"


def _b64(content: str | None) -> str:
    return base64.b64encode((content or "").encode()).decode()


def _org_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _user_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _upsert_file(url: str, headers: dict, content: str | None, message: str) -> None:
    """
    Shared core: PUT a single file to any GitHub repo.
    Fetches existing SHA first so it works as both create and update.
    """
    if content is None:
        return
    async with httpx.AsyncClient() as client:
        existing = await client.get(url, headers=headers)
    payload: dict = {"message": message, "content": _b64(content)}
    if existing.is_success:
        payload["sha"] = existing.json()["sha"]
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, headers=headers, json=payload)
    if not resp.is_success:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Failed to write {url}: {resp.text}",
        )


async def create_org_repo(slug: str, description: str) -> dict:
    """Create or fetch a repo in the organisation account."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/orgs/{settings.GITHUB_ORG}/repos",
            headers=_org_headers(),
            json={
                "name": slug,
                "description": description[:255],
                "private": False,
                "auto_init": True,
            },
        )
    if resp.status_code == 422:  # already exists
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{settings.GITHUB_ORG}/{slug}",
                headers=_org_headers(),
            )
    if not resp.is_success:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"GitHub org repo creation failed: {resp.text}",
        )
    return resp.json()


async def upsert_org_file(slug: str, path: str, content: str | None, message: str) -> None:
    """Write a file to the org repo."""
    url = f"{GITHUB_API}/repos/{settings.GITHUB_ORG}/{slug}/contents/{path}"
    await _upsert_file(url, _org_headers(), content, message)


async def create_user_repo(slug: str, description: str, token: str) -> dict:
    """Create or fetch a private repo in the user's own GitHub account."""
    headers = _user_headers(token)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/user/repos",
            headers=headers,
            json={
                "name": slug,
                "description": description[:255],
                "private": True,
                "auto_init": True,
            },
        )
    if resp.status_code == 422:  # already exists
        async with httpx.AsyncClient() as client:
            me = await client.get(f"{GITHUB_API}/user", headers=headers)
        if not me.is_success:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not fetch GitHub user info")
        username = me.json()["login"]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{username}/{slug}",
                headers=headers,
            )
    if not resp.is_success:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"GitHub user repo creation failed: {resp.text}",
        )
    return resp.json()


async def upsert_user_file(
    username: str, slug: str, path: str, content: str | None, message: str, token: str
) -> None:
    """Write a file to the user's repo."""
    url = f"{GITHUB_API}/repos/{username}/{slug}/contents/{path}"
    await _upsert_file(url, _user_headers(token), content, message)
