"""
match_skills() tests — contract for app/services/skill_matcher.py (Dev B).
These tests will fail until Dev B implements match_skills().

All httpx calls are mocked — never hits real skills.sh.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaCategory, SkillSourceRegistry
from app.models.skill import Skill
from app.services.skill_matcher import match_skills


def _make_skill_payload(slug: str) -> dict:
    return {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "description": f"Description for {slug}",
        "content": f"Content for {slug}",
        "category": PersonaCategory.DEVELOPMENT,
        "source_registry": SkillSourceRegistry.SKILLS_SH,
        "tags": [],
        "source_url": None,
        "source_author": None,
    }


async def _seed_anvila_skills(db: AsyncSession, count: int = 2) -> list[Skill]:
    skills = []
    for i in range(count):
        skill = Skill(
            name=f"Anvila Default {i}",
            slug=f"anvila-default-{i}",
            description="seeded default skill",
            content="content",
            category=PersonaCategory.DEVELOPMENT,
            source_registry=SkillSourceRegistry.ANVILA,
            is_active=True,
        )
        db.add(skill)
        skills.append(skill)
    await db.commit()
    for s in skills:
        await db.refresh(s)
    return skills


# ── skills.sh returns a match ─────────────────────────────────────────────────


async def test_skillsh_match_included_in_result(db_session: AsyncSession):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _make_skill_payload("python")

    with patch("app.services.skill_matcher.httpx.AsyncClient") as MockClient:
        mock_get = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__.return_value.get = mock_get

        result = await match_skills(["python"], PersonaCategory.DEVELOPMENT, db_session)

    assert len(result) >= 1
    slugs = [s.slug for s in result]
    assert "python" in slugs


# ── skills.sh returns 404 → local DB fallback ─────────────────────────────────


async def test_skillsh_404_falls_back_to_local_db(db_session: AsyncSession):
    local_skill = Skill(
        name="Local Python",
        slug="python",
        description="local fallback",
        content="content",
        category=PersonaCategory.DEVELOPMENT,
        source_registry=SkillSourceRegistry.ANVILA,
        is_active=True,
    )
    db_session.add(local_skill)
    await db_session.commit()
    await db_session.refresh(local_skill)

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("app.services.skill_matcher.httpx.AsyncClient") as MockClient:
        mock_get = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__.return_value.get = mock_get

        result = await match_skills(["python"], PersonaCategory.DEVELOPMENT, db_session)

    assert any(s.slug == "python" for s in result)


# ── fewer than 2 resolved → padded with ANVILA defaults ──────────────────────


async def test_pads_with_anvila_defaults_when_under_minimum(db_session: AsyncSession):
    await _seed_anvila_skills(db_session, count=2)

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("app.services.skill_matcher.httpx.AsyncClient") as MockClient:
        mock_get = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__.return_value.get = mock_get

        result = await match_skills(
            ["nonexistent-slug"], PersonaCategory.DEVELOPMENT, db_session
        )

    assert len(result) >= 2


async def test_empty_slugs_returns_anvila_defaults(db_session: AsyncSession):
    await _seed_anvila_skills(db_session, count=2)

    with patch("app.services.skill_matcher.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = AsyncMock()

        result = await match_skills([], PersonaCategory.DEVELOPMENT, db_session)

    assert len(result) >= 2


# ── never raises when skills.sh unreachable ───────────────────────────────────


async def test_does_not_raise_when_skillsh_unreachable(db_session: AsyncSession):
    await _seed_anvila_skills(db_session, count=2)

    with patch("app.services.skill_matcher.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("connection refused")
        )

        result = await match_skills(["python"], PersonaCategory.DEVELOPMENT, db_session)

    assert isinstance(result, list)
    assert len(result) >= 2


async def test_does_not_raise_on_timeout(db_session: AsyncSession):
    import httpx

    await _seed_anvila_skills(db_session, count=2)

    with patch("app.services.skill_matcher.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )

        result = await match_skills(["python"], PersonaCategory.DEVELOPMENT, db_session)

    assert isinstance(result, list)
