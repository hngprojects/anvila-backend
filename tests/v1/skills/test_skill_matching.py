import httpx
import pytest

from app.services.openclaw_client import (
    _extract_list,
    fetch_openclaw_skill,
    fetch_openclaw_skill_markdown,
    list_openclaw_skills,
    search_openclaw_skills,
)


@pytest.mark.asyncio
async def test_list_openclaw_skills_returns_items(monkeypatch):
    async def mock_get(self, url, params=None):
        assert url.endswith("/skills")
        assert params["limit"] == 10
        assert params["nonSuspiciousOnly"] == "true"

        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "slug": "web-development",
                        "displayName": "Web Development",
                        "summary": "Build web apps.",
                    }
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await list_openclaw_skills(limit=10)

    assert len(result) == 1
    assert result[0]["slug"] == "web-development"


@pytest.mark.asyncio
async def test_search_openclaw_skills_returns_results(monkeypatch):
    async def mock_get(self, url, params=None):
        assert url.endswith("/search")
        assert params["q"] == "agent"
        assert params["limit"] == 5
        assert params["nonSuspiciousOnly"] == "true"

        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "slug": "agent-usage-stats",
                        "displayName": "Token Stats",
                        "summary": "Monitor token usage.",
                    }
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await search_openclaw_skills("agent")

    assert len(result) == 1
    assert result[0]["displayName"] == "Token Stats"


@pytest.mark.asyncio
async def test_fetch_openclaw_skill_returns_payload(monkeypatch):
    async def mock_get(self, url):
        assert url.endswith("/skills/web-development")

        return httpx.Response(
            200,
            json={
                "slug": "web-development",
                "displayName": "Web Development",
                "summary": "Build web apps.",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await fetch_openclaw_skill("web-development")

    assert result is not None
    assert result["slug"] == "web-development"


@pytest.mark.asyncio
async def test_fetch_openclaw_skill_returns_none_on_http_error(monkeypatch):
    async def mock_get(self, url):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await fetch_openclaw_skill("bad-skill")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_openclaw_skill_markdown_returns_text(monkeypatch):
    async def mock_get(self, url):
        assert url.endswith("/skills/web-development/file?path=skill.md")

        return httpx.Response(
            200,
            text="# Web Development\nBuild web apps.",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await fetch_openclaw_skill_markdown("web-development")

    assert result.startswith("# Web Development")


@pytest.mark.asyncio
async def test_fetch_openclaw_skill_markdown_returns_empty_on_error(monkeypatch):
    async def mock_get(self, url):
        raise httpx.ConnectError("network failed")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await fetch_openclaw_skill_markdown("missing-skill")

    assert result == ""


def test_extract_list_supports_openclaw_shapes():
    assert _extract_list({"results": [{"slug": "a"}]}) == [{"slug": "a"}]
    assert _extract_list({"items": [{"slug": "b"}]}) == [{"slug": "b"}]
    assert _extract_list({"data": [{"slug": "c"}]}) == [{"slug": "c"}]
    assert _extract_list([]) == []
    assert _extract_list({"unknown": []}) == []
