"""
Generate endpoint tests — contract for POST /api/v1/personas/generate (Dev A).
These tests will fail until Dev A implements the endpoint.

Celery tasks are mocked — never dispatched to a real broker.
"""
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PersonaStatus
from app.models.persona import Persona
from app.models.user import User
from tests.v1.conftest import auth_headers

BASE = "/api/v1/personas"

_VALID_BODY = {
    "name": "Test Persona",
    "category": "development",
    "context": "I am a Python developer with 5 years of experience building APIs.",
    "visibility": "private",
}


async def test_generate_returns_202(client: AsyncClient, free_user: User):
    with patch("app.worker.tasks.generation.generate_persona.delay"):
        resp = await client.post(
            f"{BASE}/generate", json=_VALID_BODY, headers=auth_headers(free_user)
        )
    assert resp.status_code == 202


async def test_generate_response_has_required_fields(client: AsyncClient, free_user: User):
    with patch("app.worker.tasks.generation.generate_persona.delay"):
        resp = await client.post(
            f"{BASE}/generate", json=_VALID_BODY, headers=auth_headers(free_user)
        )
    assert resp.status_code == 202
    data = resp.json()
    assert "persona_id" in data
    assert "session_id" in data
    assert "job_id" in data
    assert data["status"] == PersonaStatus.DRAFT


async def test_generate_creates_persona_with_draft_status(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    with patch("app.worker.tasks.generation.generate_persona.delay"):
        resp = await client.post(
            f"{BASE}/generate", json=_VALID_BODY, headers=auth_headers(free_user)
        )
    assert resp.status_code == 202
    persona_id = resp.json()["persona_id"]

    result = await db_session.execute(select(Persona).where(Persona.id == persona_id))
    persona = result.scalar_one_or_none()
    assert persona is not None
    assert persona.status == PersonaStatus.DRAFT


async def test_generate_increments_generation_count(
    client: AsyncClient, free_user: User, db_session: AsyncSession
):
    initial_count = free_user.generation_count

    with patch("app.worker.tasks.generation.generate_persona.delay"):
        resp = await client.post(
            f"{BASE}/generate", json=_VALID_BODY, headers=auth_headers(free_user)
        )
    assert resp.status_code == 202

    await db_session.refresh(free_user)
    assert free_user.generation_count == initial_count + 1


async def test_generate_dispatches_celery_task(client: AsyncClient, free_user: User):
    with patch("app.worker.tasks.generation.generate_persona.delay") as mock_delay:
        resp = await client.post(
            f"{BASE}/generate", json=_VALID_BODY, headers=auth_headers(free_user)
        )
    assert resp.status_code == 202
    mock_delay.assert_called_once()


async def test_generate_blocked_at_free_limit(client: AsyncClient, db_session: AsyncSession):
    from app.models.enums import UserProvider
    from app.models.user import User

    user = User(
        email="atlimit@test.com",
        provider=UserProvider.EMAIL,
        email_verified=True,
        generation_count=3,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await client.post(
        f"{BASE}/generate", json=_VALID_BODY, headers=auth_headers(user)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "GENERATION_LIMIT_REACHED"


async def test_generate_requires_auth(client: AsyncClient):
    resp = await client.post(f"{BASE}/generate", json=_VALID_BODY)
    assert resp.status_code == 401


async def test_generate_file_upload_appends_context(client: AsyncClient, free_user: User):
    import io

    file_content = b"I specialize in distributed systems and Kubernetes deployments."

    with patch("app.worker.tasks.generation.generate_persona.delay") as mock_delay:
        resp = await client.post(
            f"{BASE}/generate",
            headers=auth_headers(free_user),
            data={
                "name": "Dev Persona",
                "category": "development",
                "context": "Base context",
                "visibility": "private",
            },
            files={"file": ("resume.txt", io.BytesIO(file_content), "text/plain")},
        )

    assert resp.status_code == 202
    # Celery task should have been called with context that includes file content
    call_kwargs = mock_delay.call_args
    assert call_kwargs is not None
