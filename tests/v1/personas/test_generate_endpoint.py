import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.persona import Persona
from app.models.user import User


@pytest.fixture(autouse=True)
def _stub_celery_dispatch(mocker):
    """All endpoint tests stub the Celery .delay() call so we never enqueue
    against a real broker. Tests that need to assert on the dispatch args use
    the returned mock via the fixture's return value, fetched with
    request.getfixturevalue or by re-patching."""
    return mocker.patch(
        "app.api.endpoints.personas.generate_persona.delay",
        return_value=SimpleNamespace(id="celery-task-id-stub"),
    )


async def test_unauthenticated_returns_401(client) -> None:
    response = await client.post(
        "/api/v1/personas/generate",
        data={"prompt": "build a sales bot"},
    )
    assert response.status_code == 401


async def test_free_user_at_generation_cap_returns_403(
    client, db_session: AsyncSession, test_user: User, auth_headers
) -> None:
    test_user.generation_count = 3
    await db_session.commit()

    response = await client.post(
        "/api/v1/personas/generate",
        data={"prompt": "build something"},
        headers=auth_headers,
    )
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["code"] == "GENERATION_LIMIT_REACHED"


async def test_happy_path_creates_persona_session_message(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
    _stub_celery_dispatch,
) -> None:
    response = await client.post(
        "/api/v1/personas/generate",
        data={"prompt": "build a tier-1 SaaS support agent"},
        headers=auth_headers,
    )
    assert response.status_code == 202
    body = response.json()
    data = body["data"]
    assert data["status"] == "queued"
    assert data["job_id"] == "celery-task-id-stub"

    persona = await db_session.get(Persona, uuid.UUID(data["persona_id"]))
    assert persona is not None
    assert persona.user_id == test_user.id
    assert persona.job_id == "celery-task-id-stub"

    session = await db_session.get(ChatSession, uuid.UUID(data["session_id"]))
    assert session is not None
    assert session.persona_id == persona.id

    messages = (
        (
            await db_session.execute(
                select(ConversationMessage).where(ConversationMessage.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(messages) == 1
    assert messages[0].round_number == 0
    assert "<USER_INPUT>" in messages[0].content

    await db_session.refresh(test_user)
    assert test_user.generation_count == 1


async def test_empty_prompt_returns_422_empty_prompt(client, test_user: User, auth_headers) -> None:
    response = await client.post(
        "/api/v1/personas/generate",
        data={"prompt": "   "},
        headers=auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "EMPTY_PROMPT"


async def test_unsupported_file_type_returns_400(client, test_user: User, auth_headers) -> None:
    response = await client.post(
        "/api/v1/personas/generate",
        data={"prompt": "build a thing"},
        files={"file": ("logo.png", b"\x89PNG", "image/png")},
        headers=auth_headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_file_content_is_forwarded_to_celery_task(
    client, test_user: User, auth_headers, _stub_celery_dispatch
) -> None:
    response = await client.post(
        "/api/v1/personas/generate",
        data={"prompt": "build a thing"},
        files={"file": ("notes.txt", b"supplemental notes content", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 202
    _stub_celery_dispatch.assert_called_once()
    args = _stub_celery_dispatch.call_args.args
    # signature: generate_persona.delay(persona_id, session_id, sanitized_prompt, file_content)
    assert args[3] == "supplemental notes content"
