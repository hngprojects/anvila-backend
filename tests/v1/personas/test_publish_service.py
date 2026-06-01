import logging
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    PersonaCategory,
    PersonaStatus,
    PersonaVisibility,
    SkillSourceRegistry,
)
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.models.user import User
from app.services.publish_service import is_safe_skill_slug, publish_persona, safe_skill_files

PERSONA_MARKDOWN_PATHS = {
    "README.md",
    "identity.md",
    "soul.md",
    "dna.md",
    "overview.md",
    "heartbeat.md",
}


def _mock_github(mocker) -> AsyncMock:
    mocker.patch(
        "app.services.publish_service.create_or_get_repo",
        new=AsyncMock(
            return_value={
                "html_url": "https://github.com/anvila/persona-x",
                "clone_url": "https://github.com/anvila/persona-x.git",
                "default_branch": "main",
            }
        ),
    )
    return mocker.patch(
        "app.services.publish_service.upsert_file",
        new=AsyncMock(return_value=None),
    )


def _make_skill(
    slug: str,
    *,
    content: str,
    files: list[dict[str, str]] | None,
) -> Skill:
    return Skill(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description=f"{slug} skill",
        content=content,
        files=files,
        category=PersonaCategory.ENGINEERING,
        tags=[],
        source_registry=SkillSourceRegistry.OPENCLAW,
    )


async def _save_persona_with_skills(
    db_session: AsyncSession,
    test_user: User,
    skills: list[Skill],
) -> Persona:
    persona = Persona(
        user_id=test_user.id,
        name=f"Publish Persona {uuid.uuid4().hex[:8]}",
        slug=f"publish-persona-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.ENGINEERING,
        description_summary="Generated persona ready to publish.",
        visibility=PersonaVisibility.PUBLIC,
        status=PersonaStatus.GENERATED,
        readme_md="# Readme",
        identity_md="# Identity",
        soul_md="# Soul",
        dna_md="# DNA",
        overview_md="# Overview",
        heartbeat_md="# Heartbeat",
    )
    db_session.add(persona)
    db_session.add_all(skills)
    await db_session.flush()

    db_session.add_all([PersonaSkill(persona_id=persona.id, skill_id=skill.id) for skill in skills])
    await db_session.commit()
    await db_session.refresh(persona)
    return persona


def _paths_written(upsert_file_mock: AsyncMock) -> list[str]:
    return [call.kwargs["path"] for call in upsert_file_mock.await_args_list]


def _call_for_path(upsert_file_mock: AsyncMock, path: str):
    matches = [call for call in upsert_file_mock.await_args_list if call.kwargs["path"] == path]
    assert len(matches) == 1
    return matches[0]


def test_safe_skill_files_returns_empty_for_empty_inputs() -> None:
    assert safe_skill_files(None) == []
    assert safe_skill_files([]) == []


def test_safe_skill_files_returns_fresh_safe_entries_in_order() -> None:
    files = [
        {"path": "SKILL.md", "content": "# Skill"},
        {"path": "templates/prompt.md", "content": "Prompt"},
    ]

    result = safe_skill_files(files)

    assert result == files
    assert result is not files
    assert result[0] is not files[0]
    assert result[1] is not files[1]


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ([{"path": "../README.md", "content": "evil"}], []),
        ([{"path": "safe/../README.md", "content": "evil"}], []),
        ([{"path": "/absolute/bad.md", "content": "evil"}], []),
        ([{"path": "folder\\bad.md", "content": "evil"}], []),
        ([{"content": "missing path"}], []),
        ([{"path": "SKILL.md", "content": 123}], []),
        ([{"path": " ", "content": "blank path"}], []),
        (["not a dict"], []),
        (
            [
                {"path": "../README.md", "content": "evil"},
                {"path": "SKILL.md", "content": "# Safe"},
                {"path": "/absolute/bad.md", "content": "evil"},
            ],
            [{"path": "SKILL.md", "content": "# Safe"}],
        ),
    ],
)
def test_safe_skill_files_drops_unsafe_entries(files, expected) -> None:
    assert safe_skill_files(files) == expected


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("safe-slug", True),
        ("snake_case_slug", True),
        ("with-numbers-123", True),
        ("", False),
        ("   ", False),
        (None, False),
        (123, False),
        ("../README", False),
        ("safe/../bad", False),
        ("foo/bar", False),
        ("foo\\bar", False),
        ("..hidden", False),
        (".dotfile", False),
        ("trailing/", False),
        ("..", False),
    ],
)
def test_is_safe_skill_slug(slug, expected) -> None:
    assert is_safe_skill_slug(slug) is expected


@pytest.mark.asyncio
async def test_publish_persona_writes_folder_per_skill_when_files_present(
    db_session: AsyncSession,
    test_user: User,
    mocker,
) -> None:
    upsert_file_mock = _mock_github(mocker)
    skills = [
        _make_skill(
            "seo-analytics",
            content="# SEO Analytics",
            files=[
                {"path": "SKILL.md", "content": "# SEO Analytics"},
                {"path": "prompt.md", "content": "Track rankings."},
            ],
        ),
        _make_skill(
            "content-planner",
            content="# Content Planner",
            files=[
                {"path": "SKILL.md", "content": "# Content Planner"},
                {"path": "templates/calendar.md", "content": "Calendar"},
            ],
        ),
    ]
    persona = await _save_persona_with_skills(db_session, test_user, skills)

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert PERSONA_MARKDOWN_PATHS <= set(paths_written)
    assert "skills/seo-analytics/SKILL.md" in paths_written
    assert "skills/seo-analytics/prompt.md" in paths_written
    assert "skills/content-planner/SKILL.md" in paths_written
    assert "skills/content-planner/templates/calendar.md" in paths_written
    assert "skills/seo-analytics.md" not in paths_written
    assert "skills/content-planner.md" not in paths_written
    assert upsert_file_mock.await_count == 10

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.PUBLISHED


@pytest.mark.asyncio
async def test_publish_persona_drops_traversal_paths_from_skill_files(
    db_session: AsyncSession,
    test_user: User,
    mocker,
) -> None:
    upsert_file_mock = _mock_github(mocker)
    skill = _make_skill(
        "guarded-skill",
        content="# Safe fallback",
        files=[
            {"path": "../README.md", "content": "evil"},
            {"path": "SKILL.md", "content": "ok"},
        ],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert "skills/guarded-skill/../README.md" not in paths_written
    assert "skills/guarded-skill/SKILL.md" in paths_written
    assert "skills/guarded-skill.md" not in paths_written
    readme_call = _call_for_path(upsert_file_mock, "README.md")
    assert readme_call.kwargs["content"] == "# Readme"
    assert [call.kwargs["path"] for call in upsert_file_mock.await_args_list].count(
        "README.md"
    ) == 1
    assert all(call.kwargs["content"] != "evil" for call in upsert_file_mock.await_args_list)
    assert upsert_file_mock.await_count == 7


@pytest.mark.asyncio
async def test_publish_persona_falls_back_to_content_when_all_skill_paths_unsafe(
    db_session: AsyncSession,
    test_user: User,
    mocker,
) -> None:
    upsert_file_mock = _mock_github(mocker)
    skill = _make_skill(
        "fallback-skill",
        content="# Legacy fallback",
        files=[
            {"path": "../../evil", "content": "x"},
            {"path": "/absolute/bad", "content": "y"},
        ],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert "skills/fallback-skill/../../evil" not in paths_written
    assert "skills/fallback-skill//absolute/bad" not in paths_written
    assert "skills/fallback-skill.md" in paths_written
    fallback_call = _call_for_path(upsert_file_mock, "skills/fallback-skill.md")
    assert fallback_call.kwargs["content"] == "# Legacy fallback"
    assert upsert_file_mock.await_count == 7


@pytest.mark.asyncio
async def test_publish_persona_falls_back_to_content_md_when_skill_files_empty(
    db_session: AsyncSession,
    test_user: User,
    mocker,
) -> None:
    upsert_file_mock = _mock_github(mocker)
    skill = _make_skill("legacy-strategy", content="# Legacy", files=None)
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert PERSONA_MARKDOWN_PATHS <= set(paths_written)
    assert "skills/legacy-strategy.md" in paths_written
    legacy_call = _call_for_path(upsert_file_mock, "skills/legacy-strategy.md")
    assert legacy_call.kwargs["content"] == "# Legacy"
    assert upsert_file_mock.await_count == 7


@pytest.mark.asyncio
async def test_publish_persona_skips_skill_when_both_files_and_content_empty(
    db_session: AsyncSession,
    test_user: User,
    mocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.publish_service")
    upsert_file_mock = _mock_github(mocker)
    skill = _make_skill("empty-skill", content="", files=None)
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert PERSONA_MARKDOWN_PATHS <= set(paths_written)
    assert not any(path.startswith("skills/") for path in paths_written)
    assert upsert_file_mock.await_count == 6
    assert "skipping skill empty-skill in publish: both files and content empty" in caplog.text


@pytest.mark.asyncio
async def test_publish_persona_skips_skill_with_unsafe_slug(
    db_session: AsyncSession,
    test_user: User,
    mocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.publish_service")
    upsert_file_mock = _mock_github(mocker)
    skill = _make_skill(
        "unsafe-placeholder",
        content="# Unsafe",
        files=[{"path": "SKILL.md", "content": "# Unsafe"}],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])
    skill.slug = "../README"
    await db_session.commit()

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert set(paths_written) == PERSONA_MARKDOWN_PATHS
    assert not any(path.startswith("skills/") for path in paths_written)
    assert upsert_file_mock.await_count == 6
    assert str(skill.id) in caplog.text
    assert "'../README'" in caplog.text
    assert "refusing to write to GitHub" in caplog.text


@pytest.mark.asyncio
async def test_publish_persona_processes_safe_slugs_when_one_skill_unsafe(
    db_session: AsyncSession,
    test_user: User,
    mocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.publish_service")
    upsert_file_mock = _mock_github(mocker)
    safe_skill = _make_skill(
        "safe-skill",
        content="# Safe",
        files=[{"path": "SKILL.md", "content": "# Safe"}],
    )
    unsafe_skill = _make_skill(
        "unsafe-placeholder",
        content="# Unsafe",
        files=[{"path": "SKILL.md", "content": "# Unsafe"}],
    )
    persona = await _save_persona_with_skills(
        db_session,
        test_user,
        [safe_skill, unsafe_skill],
    )
    unsafe_skill.slug = "../README"
    await db_session.commit()

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert PERSONA_MARKDOWN_PATHS <= set(paths_written)
    assert "skills/safe-skill/SKILL.md" in paths_written
    assert "skills/../README/SKILL.md" not in paths_written
    assert "skills/../README.md" not in paths_written
    assert upsert_file_mock.await_count == 7
    assert str(unsafe_skill.id) in caplog.text
    assert "'../README'" in caplog.text
    assert "refusing to write to GitHub" in caplog.text


@pytest.mark.asyncio
async def test_publish_persona_handles_mixed_old_and_new_skills(
    db_session: AsyncSession,
    test_user: User,
    mocker,
) -> None:
    upsert_file_mock = _mock_github(mocker)
    folder_skill = _make_skill(
        "folder-skill",
        content="# Folder Skill",
        files=[{"path": "SKILL.md", "content": "# Folder Skill"}],
    )
    legacy_skill = _make_skill("legacy-skill", content="# Legacy Skill", files=[])
    persona = await _save_persona_with_skills(
        db_session,
        test_user,
        [folder_skill, legacy_skill],
    )

    await publish_persona(persona, db_session)

    paths_written = _paths_written(upsert_file_mock)
    assert "skills/folder-skill/SKILL.md" in paths_written
    assert "skills/folder-skill.md" not in paths_written
    assert "skills/legacy-skill.md" in paths_written
    folder_call = _call_for_path(upsert_file_mock, "skills/folder-skill/SKILL.md")
    legacy_call = _call_for_path(upsert_file_mock, "skills/legacy-skill.md")
    assert folder_call.kwargs["content"] == "# Folder Skill"
    assert legacy_call.kwargs["content"] == "# Legacy Skill"
    assert upsert_file_mock.await_count == 8
