import io
import logging
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.services import skill_matcher
from app.services.openclaw_client import (
    _extract_list,
    download_openclaw_skill_zip,
    fetch_openclaw_skill,
    fetch_openclaw_skill_markdown,
    list_openclaw_skills,
    search_openclaw_skills,
)


def _zip_bytes(entries: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)

    return buffer.getvalue()


@pytest.mark.asyncio
async def test_push_skill_to_org_repo_writes_folder_per_file_when_files_present(
    mocker,
):
    mocker.patch(
        "app.services.skill_matcher.create_or_get_repo",
        new=AsyncMock(return_value={}),
    )
    upsert_file_mock = mocker.patch(
        "app.services.skill_matcher.upsert_file",
        new=AsyncMock(return_value=None),
    )
    skill = Skill(
        name="Folder Skill",
        slug="folder-skill",
        description="A folder-backed skill.",
        content="# Folder Skill",
        files=[
            {"path": "SKILL.md", "content": "# Folder Skill"},
            {"path": "prompt.md", "content": "Prompt"},
        ],
        category="engineering",
        tags=[],
        source_registry="openclaw",
    )

    await skill_matcher.push_skill_to_org_repo(skill)

    paths_written = [call.kwargs["path"] for call in upsert_file_mock.await_args_list]
    assert paths_written == ["folder-skill/SKILL.md", "folder-skill/prompt.md"]
    assert "folder-skill.md" not in paths_written
    assert upsert_file_mock.await_count == 2


@pytest.mark.asyncio
async def test_push_skill_to_org_repo_falls_back_to_content_md_when_files_empty(
    mocker,
):
    mocker.patch(
        "app.services.skill_matcher.create_or_get_repo",
        new=AsyncMock(return_value={}),
    )
    upsert_file_mock = mocker.patch(
        "app.services.skill_matcher.upsert_file",
        new=AsyncMock(return_value=None),
    )
    skill = Skill(
        name="Legacy Skill",
        slug="legacy-skill",
        description="A legacy single-file skill.",
        content="# Legacy",
        files=None,
        category="engineering",
        tags=[],
        source_registry="openclaw",
    )

    await skill_matcher.push_skill_to_org_repo(skill)

    upsert_file_mock.assert_awaited_once_with(
        slug=skill_matcher.SKILLS_REPO,
        path="legacy-skill.md",
        content="# Legacy",
        message="chore: upsert skill legacy-skill",
    )


@pytest.mark.asyncio
async def test_push_skill_to_org_repo_drops_traversal_paths_from_files(
    mocker,
):
    mocker.patch(
        "app.services.skill_matcher.create_or_get_repo",
        new=AsyncMock(return_value={}),
    )
    upsert_file_mock = mocker.patch(
        "app.services.skill_matcher.upsert_file",
        new=AsyncMock(return_value=None),
    )
    skill = Skill(
        name="Guarded Skill",
        slug="guarded-skill",
        description="A folder-backed skill with one unsafe entry.",
        content="# Safe fallback",
        files=[
            {"path": "safe/../README.md", "content": "evil"},
            {"path": "SKILL.md", "content": "ok"},
        ],
        category="engineering",
        tags=[],
        source_registry="openclaw",
    )

    await skill_matcher.push_skill_to_org_repo(skill)

    paths_written = [call.kwargs["path"] for call in upsert_file_mock.await_args_list]
    assert paths_written == ["guarded-skill/SKILL.md"]
    assert "guarded-skill/safe/../README.md" not in paths_written
    assert upsert_file_mock.await_count == 1


@pytest.mark.asyncio
async def test_push_skill_to_org_repo_falls_back_to_content_when_all_paths_unsafe(
    mocker,
):
    mocker.patch(
        "app.services.skill_matcher.create_or_get_repo",
        new=AsyncMock(return_value={}),
    )
    upsert_file_mock = mocker.patch(
        "app.services.skill_matcher.upsert_file",
        new=AsyncMock(return_value=None),
    )
    skill = Skill(
        name="Fallback Skill",
        slug="fallback-skill",
        description="A folder-backed skill with only unsafe entries.",
        content="# Legacy fallback",
        files=[
            {"path": "../../README.md", "content": "x"},
            {"path": "/absolute/bad.md", "content": "y"},
        ],
        category="engineering",
        tags=[],
        source_registry="openclaw",
    )

    await skill_matcher.push_skill_to_org_repo(skill)

    upsert_file_mock.assert_awaited_once_with(
        slug=skill_matcher.SKILLS_REPO,
        path="fallback-skill.md",
        content="# Legacy fallback",
        message="chore: upsert skill fallback-skill",
    )


@pytest.mark.asyncio
async def test_push_skill_to_org_repo_skips_when_both_files_and_content_empty(
    mocker,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING, logger="app.services.skill_matcher")
    create_or_get_repo_mock = mocker.patch(
        "app.services.skill_matcher.create_or_get_repo",
        new=AsyncMock(return_value={}),
    )
    upsert_file_mock = mocker.patch(
        "app.services.skill_matcher.upsert_file",
        new=AsyncMock(return_value=None),
    )
    skill = Skill(
        name="Empty Skill",
        slug="empty-skill",
        description="An empty skill.",
        content="",
        files=None,
        category="engineering",
        tags=[],
        source_registry="openclaw",
    )

    await skill_matcher.push_skill_to_org_repo(skill)

    create_or_get_repo_mock.assert_awaited_once_with(
        slug=skill_matcher.SKILLS_REPO,
        description="Shared skill library",
    )
    upsert_file_mock.assert_not_awaited()
    assert (
        "skipping push of skill empty-skill to org repo: both files and content empty"
        in caplog.text
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


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_extracts_text_files(monkeypatch):
    async def mock_get(self, url, params=None):
        assert url.endswith("/download")
        assert params == {"slug": "web-development"}

        return httpx.Response(
            200,
            content=_zip_bytes(
                {
                    "SKILL.md": "# Web Development\nBuild web apps.",
                    "prompt.md": "Use practical examples.",
                }
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("web-development")

    assert result == [
        {"path": "SKILL.md", "content": "# Web Development\nBuild web apps."},
        {"path": "prompt.md", "content": "Use practical examples."},
    ]


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_skips_binary_files(monkeypatch):
    async def mock_get(self, url, params=None):
        return httpx.Response(
            200,
            content=_zip_bytes(
                {
                    "SKILL.md": "# Text",
                    "asset.bin": b"\xff\xfe\xfd",
                }
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("mixed-skill")

    assert result == [{"path": "SKILL.md", "content": "# Text"}]


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_skips_files_over_per_file_cap(monkeypatch):
    async def mock_get(self, url, params=None):
        return httpx.Response(
            200,
            content=_zip_bytes(
                {
                    "large.md": "x" * ((1 * 1024 * 1024) + 1),
                    "small.md": "small",
                }
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("oversized-skill")

    assert result == [{"path": "small.md", "content": "small"}]


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_truncates_when_total_exceeds_cap(
    monkeypatch,
):
    async def mock_get(self, url, params=None):
        return httpx.Response(
            200,
            content=_zip_bytes({f"file-{idx:02}.md": "x" * (1 * 1024 * 1024) for idx in range(12)}),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("large-folder-skill")

    assert len(result) < 12
    assert all(entry["content"] for entry in result)


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_skips_directory_entries(monkeypatch):
    async def mock_get(self, url, params=None):
        return httpx.Response(
            200,
            content=_zip_bytes(
                {
                    "templates/": "",
                    "templates/example.md": "Example",
                }
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("templates-skill")

    assert result == [{"path": "templates/example.md", "content": "Example"}]


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_returns_empty_on_http_error(monkeypatch):
    async def mock_get(self, url, params=None):
        raise httpx.ConnectError("network failed")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("missing-skill")

    assert result == []


@pytest.mark.asyncio
async def test_download_openclaw_skill_zip_returns_empty_on_malformed_zip(monkeypatch):
    async def mock_get(self, url, params=None):
        return httpx.Response(
            200,
            content=b"not a zip",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await download_openclaw_skill_zip("bad-zip")

    assert result == []


@pytest.mark.asyncio
async def test_upsert_populates_files_column(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    files = [
        {"path": "SKILL.md", "content": "# Folder Skill"},
        {"path": "prompt.md", "content": "Prompt text"},
    ]

    async def mock_download(slug):
        assert slug == "folder-skill"
        return files

    async def fail_legacy_fetch(skill_ref):
        raise AssertionError("legacy markdown fetch should not run")

    monkeypatch.setattr(skill_matcher, "download_openclaw_skill_zip", mock_download)
    monkeypatch.setattr(skill_matcher, "fetch_openclaw_skill_markdown", fail_legacy_fetch)

    await skill_matcher._upsert_openclaw_skill(
        item={"slug": "folder-skill"},
        detail={
            "id": "folder-skill-id",
            "slug": "folder-skill",
            "displayName": "Folder Skill",
            "summary": "A full folder skill.",
        },
        category="engineering",
        db=db_session,
    )

    result = await db_session.execute(select(Skill).where(Skill.slug == "folder-skill"))
    saved = result.scalar_one()

    assert saved.content == "# Folder Skill"
    assert saved.files == files


@pytest.mark.asyncio
async def test_upsert_sets_content_from_zip_skill_md(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    async def mock_download(slug):
        return [
            {"path": "templates/example.md", "content": "Example"},
            {"path": "SKILL.md", "content": "# Zip Skill\nFrom folder."},
        ]

    async def fail_legacy_fetch(skill_ref):
        raise AssertionError("legacy markdown fetch should not run")

    monkeypatch.setattr(skill_matcher, "download_openclaw_skill_zip", mock_download)
    monkeypatch.setattr(skill_matcher, "fetch_openclaw_skill_markdown", fail_legacy_fetch)

    await skill_matcher._upsert_openclaw_skill(
        item={"slug": "zip-skill"},
        detail={
            "id": "zip-skill-id",
            "slug": "zip-skill",
            "displayName": "Zip Skill",
            "summary": "A zip skill.",
        },
        category="engineering",
        db=db_session,
    )

    result = await db_session.execute(select(Skill).where(Skill.slug == "zip-skill"))
    saved = result.scalar_one()

    assert saved.content == "# Zip Skill\nFrom folder."
    assert saved.files == [
        {"path": "templates/example.md", "content": "Example"},
        {"path": "SKILL.md", "content": "# Zip Skill\nFrom folder."},
    ]


@pytest.mark.asyncio
async def test_upsert_falls_back_to_legacy_fetch_when_zip_lacks_skill_md(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    async def mock_download(slug):
        return [{"path": "prompt.md", "content": "Prompt only"}]

    async def mock_legacy_fetch(skill_ref):
        assert skill_ref == "legacy-skill-id"
        return "# Legacy Skill\nFrom file endpoint."

    monkeypatch.setattr(skill_matcher, "download_openclaw_skill_zip", mock_download)
    monkeypatch.setattr(skill_matcher, "fetch_openclaw_skill_markdown", mock_legacy_fetch)

    await skill_matcher._upsert_openclaw_skill(
        item={"slug": "legacy-skill"},
        detail={
            "id": "legacy-skill-id",
            "slug": "legacy-skill",
            "displayName": "Legacy Skill",
            "summary": "Needs fallback.",
        },
        category="engineering",
        db=db_session,
    )

    result = await db_session.execute(select(Skill).where(Skill.slug == "legacy-skill"))
    saved = result.scalar_one()

    assert saved.content == "# Legacy Skill\nFrom file endpoint."
    assert saved.files == [{"path": "prompt.md", "content": "Prompt only"}]


def test_extract_skill_md_matches_basename_not_endswith():
    files = [
        {"path": "my-skill.md", "content": "sibling"},
        {"path": "SKILL.md", "content": "canonical"},
    ]

    assert skill_matcher._extract_skill_md(files) == "canonical"


def test_extract_skill_md_matches_nested_skill_md():
    files = [{"path": "templates/skill.md", "content": "nested"}]

    assert skill_matcher._extract_skill_md(files) == "nested"


def test_extract_skill_md_ignores_other_md_files():
    files = [{"path": "not-skill.md", "content": "sibling"}]

    assert skill_matcher._extract_skill_md(files) == ""


@pytest.mark.asyncio
async def test_upsert_preserves_existing_content_when_new_fetch_returns_empty(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    original_files = [
        {"path": "SKILL.md", "content": "# Cached Skill"},
        {"path": "prompt.md", "content": "Prompt text"},
    ]
    download_results = [original_files, []]

    async def mock_download(slug):
        assert slug == "cached-skill"
        return download_results.pop(0)

    async def mock_legacy_fetch(skill_ref):
        assert skill_ref == "cached-skill-id"
        return ""

    monkeypatch.setattr(skill_matcher, "download_openclaw_skill_zip", mock_download)
    monkeypatch.setattr(skill_matcher, "fetch_openclaw_skill_markdown", mock_legacy_fetch)

    payload = {
        "id": "cached-skill-id",
        "slug": "cached-skill",
        "displayName": "Cached Skill",
        "summary": "A cached skill.",
    }

    await skill_matcher._upsert_openclaw_skill(
        item={"slug": "cached-skill"},
        detail=payload,
        category="engineering",
        db=db_session,
    )
    await skill_matcher._upsert_openclaw_skill(
        item={"slug": "cached-skill"},
        detail=payload,
        category="engineering",
        db=db_session,
    )

    result = await db_session.execute(select(Skill).where(Skill.slug == "cached-skill"))
    saved = result.scalar_one()

    assert saved.content == "# Cached Skill"
    assert saved.files == original_files


def test_extract_list_supports_openclaw_shapes():
    assert _extract_list({"results": [{"slug": "a"}]}) == [{"slug": "a"}]
    assert _extract_list({"items": [{"slug": "b"}]}) == [{"slug": "b"}]
    assert _extract_list({"data": [{"slug": "c"}]}) == [{"slug": "c"}]
    assert _extract_list([]) == []
    assert _extract_list({"unknown": []}) == []
