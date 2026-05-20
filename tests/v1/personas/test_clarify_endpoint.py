import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import UserPlan, UserProvider
from app.models.persona import Persona
from app.models.user import User


@pytest.fixture(autouse=True)
def _stub_redis(mocker):
    fake_client = AsyncMock()
    fake_client.publish = AsyncMock(return_value=1)
    fake_client.aclose = AsyncMock(return_value=None)
    mocker.patch(
        "app.api.endpoints.personas.Redis.from_url",
        return_value=fake_client,
    )
    return fake_client


@pytest.fixture()
async def persona_with_session(
    db_session: AsyncSession, test_user: User
) -> tuple[Persona, ChatSession]:
    persona = Persona(
        user_id=test_user.id,
        name="draft",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        category="development",
        description_summary="",
        visibility="public",
        status="needs_clarification",
    )
    db_session.add(persona)
    await db_session.flush()
    session = ChatSession(persona_id=persona.id, user_id=test_user.id)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(persona)
    await db_session.refresh(session)
    return persona, session


async def test_unauthenticated_returns_401(client, persona_with_session) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={"session_id": str(session.id), "answers": [{"id": "x", "answer": "y"}]},
    )
    assert response.status_code == 401


async def test_other_users_persona_returns_404(
    client, db_session: AsyncSession, auth_headers
) -> None:
    other_user = User(
        email=f"other-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()
    other_persona = Persona(
        user_id=other_user.id,
        name="not yours",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        category="development",
        description_summary="",
        visibility="public",
        status="draft",
    )
    db_session.add(other_persona)
    await db_session.flush()
    other_session = ChatSession(persona_id=other_persona.id, user_id=other_user.id)
    db_session.add(other_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/personas/{other_persona.id}/clarify",
        json={
            "session_id": str(other_session.id),
            "answers": [{"id": "x", "answer": "y"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_happy_path_increments_round_saves_messages_publishes_continue(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
    persona_with_session,
    _stub_redis,
) -> None:
    persona, session = persona_with_session

    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [
                {"id": "role", "answer": "tier-1 support agent"},
                {"id": "audience", "answer": "smb saas customers"},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "clarifying"
    assert body["data"]["round"] == 1

    await db_session.refresh(session)
    assert session.clarification_round == 1
    assert session.compressed_context is not None
    assert "Q: role" in session.compressed_context

    messages = (
        (
            await db_session.execute(
                select(ConversationMessage).where(ConversationMessage.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(messages) == 2

    _stub_redis.publish.assert_awaited_once()
    channel_arg = _stub_redis.publish.await_args.args[0]
    payload_arg = _stub_redis.publish.await_args.args[1]
    assert channel_arg == f"persona:{persona.id}:continue"
    assert '"type": "continue"' in payload_arg


async def test_cap_reached_returns_409_and_does_not_increment(
    client,
    db_session: AsyncSession,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    session.clarification_round = 5
    await db_session.commit()

    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={"session_id": str(session.id), "answers": [{"id": "x", "answer": "y"}]},
        headers=auth_headers,
    )
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "MAX_ROUNDS_REACHED"

    await db_session.refresh(session)
    assert session.clarification_round == 5


async def test_all_empty_answers_returns_422_empty_answers(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session

    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [
                {"id": "a", "answer": "   "},
                {"id": "b", "answer": "\n\n\n"},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "EMPTY_ANSWERS"


async def test_answer_id_with_invalid_characters_returns_422(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [{"id": "Has Spaces", "answer": "valid answer body"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_answer_id_with_html_brackets_returns_422(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [{"id": "id<script>", "answer": "valid answer body"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_answer_id_with_newline_returns_422(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [{"id": "id\nrole", "answer": "valid answer body"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_answer_id_with_uppercase_returns_422(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [{"id": "RoleField", "answer": "valid answer body"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_answer_too_long_returns_422(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [{"id": "role", "answer": "a" * 4001}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_more_than_ten_answers_returns_422(
    client,
    auth_headers,
    persona_with_session,
) -> None:
    persona, session = persona_with_session
    response = await client.post(
        f"/api/v1/personas/{persona.id}/clarify",
        json={
            "session_id": str(session.id),
            "answers": [{"id": f"q_{i}", "answer": "valid"} for i in range(11)],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
