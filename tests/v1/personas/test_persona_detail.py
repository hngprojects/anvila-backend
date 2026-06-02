import uuid

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


def _make_skill(
    slug: str,
    *,
    content: str = "# Legacy content",
    files: list[object] | None = None,
    tags: list[str] | None = None,
) -> Skill:
    return Skill(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description=f"{slug} detail skill",
        content=content,
        files=files,
        category=PersonaCategory.ENGINEERING,
        tags=["detail"] if tags is None else tags,
        source_registry=SkillSourceRegistry.OPENCLAW,
    )


async def _save_persona_with_skills(
    db_session: AsyncSession,
    test_user: User,
    skills: list[Skill],
) -> Persona:
    persona = Persona(
        user_id=test_user.id,
        name=f"Detail Persona {uuid.uuid4().hex[:8]}",
        slug=f"detail-persona-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.ENGINEERING,
        description_summary="Detailed persona summary.",
        visibility=PersonaVisibility.PUBLIC,
        status=PersonaStatus.GENERATED,
        github_repo_url="https://github.com/anvila/detail-persona",
        github_clone_url="https://github.com/anvila/detail-persona.git",
        github_zip_url="https://github.com/anvila/detail-persona/archive/refs/heads/main.zip",
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


async def _get_detail_data(client, persona: Persona, auth_headers: dict[str, str]) -> dict:
    response = await client.get(f"/api/v1/personas/{persona.id}", headers=auth_headers)
    assert response.status_code == 200
    return response.json()["data"]


async def test_detail_includes_skill_files_when_present(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    skill = _make_skill(
        "folder-skill",
        files=[
            {"path": "SKILL.md", "content": "# X"},
            {"path": "scripts/run.py", "content": "print(1)"},
        ],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    data = await _get_detail_data(client, persona, auth_headers)

    skills = data["skills"]
    assert len(skills) == 1
    files = skills[0]["files"]
    assert files == [
        {"path": "SKILL.md", "content": "# X"},
        {"path": "scripts/run.py", "content": "print(1)"},
    ]
    assert {file["path"] for file in files} == {"SKILL.md", "scripts/run.py"}


async def test_detail_skill_files_empty_for_legacy_null(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    skill = _make_skill(
        "legacy-null",
        content="# Legacy fallback",
        files=None,
        tags=["legacy", "null"],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    data = await _get_detail_data(client, persona, auth_headers)

    response_skill = data["skills"][0]
    assert response_skill["files"] == []
    assert response_skill["slug"] == "legacy-null"
    assert response_skill["name"] == "Legacy Null"
    assert response_skill["description"] == "legacy-null detail skill"
    assert response_skill["tags"] == ["legacy", "null"]


async def test_detail_skill_files_empty_for_empty_list(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    skill = _make_skill("legacy-empty", content="# Legacy fallback", files=[])
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    data = await _get_detail_data(client, persona, auth_headers)

    assert data["skills"][0]["files"] == []


async def test_detail_drops_unsafe_path_entries(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    skill = _make_skill(
        "guarded-skill",
        files=[
            {"path": "SKILL.md", "content": "ok"},
            {"path": "../escape.md", "content": "bad"},
        ],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    data = await _get_detail_data(client, persona, auth_headers)

    files = data["skills"][0]["files"]
    assert files == [{"path": "SKILL.md", "content": "ok"}]
    assert "../escape.md" not in {file["path"] for file in files}


async def test_detail_drops_malformed_entries(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    skill = _make_skill(
        "malformed-skill",
        files=[
            {"path": "SKILL.md"},
            "notadict",
            {"path": "ok.md", "content": "yes"},
        ],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    data = await _get_detail_data(client, persona, auth_headers)

    assert data["skills"][0]["files"] == [{"path": "ok.md", "content": "yes"}]


async def test_detail_other_fields_unchanged(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    skill = _make_skill(
        "unchanged-fields",
        files=[{"path": "SKILL.md", "content": "# Skill"}],
        tags=["stable"],
    )
    persona = await _save_persona_with_skills(db_session, test_user, [skill])

    data = await _get_detail_data(client, persona, auth_headers)

    assert data["id"] == str(persona.id)
    assert data["name"] == persona.name
    assert data["description_summary"] == "Detailed persona summary."
    assert data["category"] == "engineering"
    assert data["status"] == "generated"
    assert data["visibility"] == "public"
    assert data["github_repo_url"] == "https://github.com/anvila/detail-persona"
    assert data["github_clone_url"] == "https://github.com/anvila/detail-persona.git"
    assert (
        data["github_zip_url"]
        == "https://github.com/anvila/detail-persona/archive/refs/heads/main.zip"
    )
    assert data["identity_md"] == "# Identity"
    assert data["soul_md"] == "# Soul"
    assert data["dna_md"] == "# DNA"
    assert data["overview_md"] == "# Overview"
    assert data["heartbeat_md"] == "# Heartbeat"
    assert data["readme_md"] == "# Readme"

    skills = data["skills"]
    assert len(skills) == 1
    assert skills[0]["slug"] == "unchanged-fields"
    assert skills[0]["name"] == "Unchanged Fields"
    assert skills[0]["description"] == "unchanged-fields detail skill"
    assert skills[0]["tags"] == ["stable"]
    assert skills[0]["files"] == [{"path": "SKILL.md", "content": "# Skill"}]
