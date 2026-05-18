"""
Clarify endpoint tests — contract for POST /api/v1/personas/{id}/clarify (Dev A).
These tests will fail until Dev A implements the endpoint.
"""
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.enums import PersonaCategory, PersonaStatus, PersonaVisibility, SessionStatus
from app.models.persona import Persona
from app.models.user import User
from tests.v1.conftest import auth_headers

BASE = "/api/v1/personas"


async def _create_persona_with_session(
    db: AsyncSession, user: User, clarification_round: int = 0
) -> tuple[Persona, ChatSession]:
    persona = Persona(
        user_id=user.id,
        name="Test Persona",
        slug=f"test-persona-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="A test persona",
        visibility=PersonaVisibility.PRIVATE,
        status=PersonaStatus.NEEDS_CLARIFICATION,
    )
    db.add(persona)
    await db.flush()

    session = ChatSession(
        persona_id=persona.id,
        user_id=user.id,
        status=SessionStatus.ACTIVE,
        clarification_round=clarification_round,
    )
    db.add(session)
    await db.commit()
    await db.refresh(persona)
    await db.refresh(session)
    return persona, session


_CLARIFY_ANSWERS = {
    "answers": [
        {"id": "q1", "answer": "I primarily work with FastAPI and PostgreSQL."},
        {"id": "q2", "answer": "About 3 years of professional experience."},
    ]
}


async def test_clarify_increments_round(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona, session = await _create_persona_with_session(db_session, free_user, clarification_round=0)

    with patch("app.worker.tasks.generation.generate_persona.apply_async"):
        resp = await client.post(
            f"{BASE}/{persona.id}/clarify",
            json=_CLARIFY_ANSWERS,
            headers=auth_headers(free_user),
        )

    assert resp.status_code == 200
    await db_session.refresh(session)
    assert session.clarification_round == 1


async def test_clarify_updates_compressed_context(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona, session = await _create_persona_with_session(db_session, free_user)

    with patch("app.worker.tasks.generation.generate_persona.apply_async"):
        resp = await client.post(
            f"{BASE}/{persona.id}/clarify",
            json=_CLARIFY_ANSWERS,
            headers=auth_headers(free_user),
        )

    assert resp.status_code == 200
    await db_session.refresh(session)
    assert session.compressed_context is not None
    assert len(session.compressed_context) > 0


async def test_clarify_returns_409_at_max_rounds(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    persona, session = await _create_persona_with_session(
        db_session, free_user, clarification_round=5
    )

    resp = await client.post(
        f"{BASE}/{persona.id}/clarify",
        json=_CLARIFY_ANSWERS,
        headers=auth_headers(free_user),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MAX_ROUNDS_REACHED"


async def test_clarify_persona_not_found(client: AsyncClient, free_user: User):
    resp = await client.post(
        f"{BASE}/{uuid.uuid4()}/clarify",
        json=_CLARIFY_ANSWERS,
        headers=auth_headers(free_user),
    )
    assert resp.status_code == 404


async def test_clarify_requires_auth(client: AsyncClient, free_user: User, db_session: AsyncSession):
    persona, _ = await _create_persona_with_session(db_session, free_user)
    resp = await client.post(f"{BASE}/{persona.id}/clarify", json=_CLARIFY_ANSWERS)
    assert resp.status_code == 401
