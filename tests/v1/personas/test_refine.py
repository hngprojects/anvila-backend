"""
Refine endpoint tests — contract for POST /api/v1/personas/{id}/refine (Dev A).
These tests will fail until Dev A implements the endpoint.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaCategory, PersonaStatus, PersonaVisibility
from app.models.persona import Persona
from app.models.user import User
from tests.v1.conftest import auth_headers

BASE = "/api/v1/personas"


async def _create_generated_persona(db: AsyncSession, user: User) -> Persona:
    persona = Persona(
        user_id=user.id,
        name="Generated Persona",
        slug=f"generated-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="A generated test persona",
        visibility=PersonaVisibility.PRIVATE,
        status=PersonaStatus.GENERATED,
        identity_md="# Identity\nTest identity",
        soul_md="# Soul\nTest soul",
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    return persona


_REFINE_BODY = {
    "instructions": "Make the persona more focused on backend engineering.",
}


async def test_refine_sets_refine_used_for_free_user(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _create_generated_persona(db_session, free_user)

    resp = await client.post(
        f"{BASE}/{persona.id}/refine",
        json=_REFINE_BODY,
        headers=auth_headers(free_user),
    )
    assert resp.status_code == 200
    await db_session.refresh(free_user)
    assert free_user.refine_used is True


async def test_refine_second_attempt_by_free_user_blocked(
    client: AsyncClient, db_session: AsyncSession
):
    from app.models.enums import UserProvider

    user = User(
        email="refined@test.com",
        provider=UserProvider.EMAIL,
        email_verified=True,
        refine_used=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    persona = await _create_generated_persona(db_session, user)

    resp = await client.post(
        f"{BASE}/{persona.id}/refine",
        json=_REFINE_BODY,
        headers=auth_headers(user),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "REFINE_LIMIT_REACHED"


async def test_refine_paid_user_can_refine_multiple_times(
    client: AsyncClient, paid_user: User, db_session: AsyncSession
):
    persona = await _create_generated_persona(db_session, paid_user)

    for _ in range(3):
        resp = await client.post(
            f"{BASE}/{persona.id}/refine",
            json=_REFINE_BODY,
            headers=auth_headers(paid_user),
        )
        assert resp.status_code == 200


async def test_refine_updates_token_counts(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _create_generated_persona(db_session, free_user)
    initial_persona_tokens = persona.tokens_used
    initial_user_tokens = free_user.total_tokens_used

    resp = await client.post(
        f"{BASE}/{persona.id}/refine",
        json=_REFINE_BODY,
        headers=auth_headers(free_user),
    )
    assert resp.status_code == 200

    await db_session.refresh(persona)
    await db_session.refresh(free_user)
    assert persona.tokens_used >= initial_persona_tokens
    assert free_user.total_tokens_used >= initial_user_tokens


async def test_refine_invalid_file_key_returns_400(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = await _create_generated_persona(db_session, free_user)

    resp = await client.post(
        f"{BASE}/{persona.id}/refine",
        json={**_REFINE_BODY, "file_key": "nonexistent_file.pdf"},
        headers=auth_headers(free_user),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_FILE_KEY"


async def test_refine_draft_persona_returns_409(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona = Persona(
        user_id=free_user.id,
        name="Draft Persona",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="draft",
        visibility=PersonaVisibility.PRIVATE,
        status=PersonaStatus.DRAFT,
    )
    db_session.add(persona)
    await db_session.commit()
    await db_session.refresh(persona)

    resp = await client.post(
        f"{BASE}/{persona.id}/refine",
        json=_REFINE_BODY,
        headers=auth_headers(free_user),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "PERSONA_NOT_READY"


async def test_refine_requires_auth(client: AsyncClient, free_user: User, db_session: AsyncSession):
    persona = await _create_generated_persona(db_session, free_user)
    resp = await client.post(f"{BASE}/{persona.id}/refine", json=_REFINE_BODY)
    assert resp.status_code == 401
