"""
Explore endpoint tests — contract for GET /api/v1/explore (Dev A or whomever owns it).
These tests will fail until the endpoint is implemented.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaCategory, PersonaStatus, PersonaVisibility
from app.models.persona import Persona
from app.models.user import User
from tests.v1.conftest import auth_headers

BASE = "/api/v1/explore"


async def _make_persona(
    db: AsyncSession,
    user: User,
    *,
    status: PersonaStatus = PersonaStatus.PUBLISHED,
    visibility: PersonaVisibility = PersonaVisibility.PUBLIC,
    is_listed: bool = True,
    deleted_at=None,
    name: str = "Explore Persona",
    description_summary: str = "A great persona for exploring.",
) -> Persona:
    persona = Persona(
        user_id=user.id,
        name=name,
        slug=f"explore-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary=description_summary,
        visibility=visibility,
        status=status,
        is_listed=is_listed,
        deleted_at=deleted_at,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    return persona


async def test_published_public_listed_persona_appears(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _make_persona(db_session, free_user)
    resp = await client.get(BASE)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["personas"]]
    assert str(persona.id) in ids


async def test_unpublished_persona_does_not_appear(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _make_persona(
        db_session, free_user, status=PersonaStatus.DRAFT, is_listed=True
    )
    resp = await client.get(BASE)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["personas"]]
    assert str(persona.id) not in ids


async def test_private_persona_does_not_appear(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _make_persona(
        db_session, free_user, visibility=PersonaVisibility.PRIVATE
    )
    resp = await client.get(BASE)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["personas"]]
    assert str(persona.id) not in ids


async def test_unlisted_persona_does_not_appear(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _make_persona(db_session, free_user, is_listed=False)
    resp = await client.get(BASE)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["personas"]]
    assert str(persona.id) not in ids


async def test_soft_deleted_persona_does_not_appear(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    from datetime import datetime, timezone

    persona = await _make_persona(
        db_session, free_user, deleted_at=datetime.now(timezone.utc)
    )
    resp = await client.get(BASE)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["personas"]]
    assert str(persona.id) not in ids


async def test_search_filter_matches_name(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    await _make_persona(db_session, free_user, name="Python Expert")
    await _make_persona(db_session, free_user, name="Java Specialist")

    resp = await client.get(f"{BASE}?search=Python")
    assert resp.status_code == 200
    personas = resp.json()["personas"]
    names = [p["name"] for p in personas]
    assert any("Python" in n for n in names)
    assert not any("Java" in n for n in names)


async def test_search_filter_matches_description(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    await _make_persona(
        db_session,
        free_user,
        name="Generic Dev",
        description_summary="Expert in machine learning pipelines",
    )

    resp = await client.get(f"{BASE}?search=machine+learning")
    assert resp.status_code == 200
    personas = resp.json()["personas"]
    assert len(personas) >= 1
