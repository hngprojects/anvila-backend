import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.personas import _relay_refine
from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import MessageRole, PersonaCategory, PersonaStatus, UserPlan, UserProvider
from app.models.persona import Persona
from app.models.user import User


class FakePubSub:
    def __init__(self, messages: list[dict], order: list[str] | None = None) -> None:
        self.messages = list(messages)
        self.order = order if order is not None else []
        self.subscribed_channel: str | None = None
        self.subscribe = AsyncMock(side_effect=self._subscribe)
        self.unsubscribe = AsyncMock()
        self.aclose = AsyncMock()

    async def _subscribe(self, channel: str) -> None:
        self.subscribed_channel = channel
        self.order.append("subscribe")

    async def get_message(self, **kwargs):
        if not self.messages:
            return None
        return {"type": "message", "data": json.dumps(self.messages.pop(0))}


class FakeRedisClient:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub
        self.aclose = AsyncMock()

    def pubsub(self) -> FakePubSub:
        return self._pubsub


def _patch_relay_redis(
    mocker,
    messages: list[dict] | None = None,
    order: list[str] | None = None,
) -> FakePubSub:
    pubsub = FakePubSub(messages or [{"type": "done"}], order)
    mocker.patch(
        "app.api.endpoints.personas.aioredis.from_url",
        return_value=FakeRedisClient(pubsub),
    )
    return pubsub


def _patch_delay(mocker, order: list[str] | None = None):
    def _delay(*args):
        if order is not None:
            order.append("delay")
        return SimpleNamespace(id="refine-task-id")

    return mocker.patch("app.api.endpoints.personas.refine_persona.delay", side_effect=_delay)


async def _make_persona(
    db_session: AsyncSession,
    user: User,
    *,
    status: PersonaStatus = PersonaStatus.GENERATED,
    deleted: bool = False,
) -> tuple[Persona, ChatSession]:
    persona = Persona(
        user_id=user.id,
        name="Endpoint Persona",
        slug=f"endpoint-refine-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.SUPPORT,
        description_summary="Support persona",
        visibility="public",
        status=status,
        identity_md="# Identity",
        soul_md="# Soul",
        dna_md="# DNA",
        overview_md="# Overview",
        heartbeat_md="# Heartbeat",
        readme_md="# Readme",
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db_session.add(persona)
    await db_session.flush()
    session = ChatSession(persona_id=persona.id, user_id=user.id)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(persona)
    await db_session.refresh(session)
    return persona, session


async def _user_messages(db_session: AsyncSession, session: ChatSession):
    result = await db_session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.session_id == session.id,
            ConversationMessage.role == MessageRole.USER,
        )
        .order_by(ConversationMessage.created_at)
    )
    return list(result.scalars().all())


async def test_owner_generated_returns_sse_enqueues_and_persists_user_message(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
    mocker,
) -> None:
    persona, session = await _make_persona(db_session, test_user)
    _patch_relay_redis(mocker, [{"type": "token", "text": "ok"}, {"type": "done"}])
    delay = _patch_delay(mocker)

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "Can it handle escalations?"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: start" in response.text
    assert "event: token" in response.text
    assert "event: done" in response.text

    delay.assert_called_once()
    args = delay.call_args.args
    assert args[0] == str(persona.id)
    assert args[1] == str(session.id)
    assert args[2].startswith(f"persona:{persona.id}:refine:")
    assert args[3] == "<USER_INPUT>\nCan it handle escalations?\n</USER_INPUT>"

    messages = await _user_messages(db_session, session)
    assert len(messages) == 1
    assert messages[0].content == "<USER_INPUT>\nCan it handle escalations?\n</USER_INPUT>"
    assert messages[0].round_number == 0


async def test_owner_published_is_allowed(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
    mocker,
) -> None:
    persona, _session = await _make_persona(
        db_session,
        test_user,
        status=PersonaStatus.PUBLISHED,
    )
    _patch_relay_redis(mocker, [{"type": "complete", "persona_id": str(persona.id)}])
    delay = _patch_delay(mocker)

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "Regenerate the tone."},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "event: complete" in response.text
    delay.assert_called_once()


async def test_status_not_refinable_returns_409(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    persona, _session = await _make_persona(db_session, test_user, status=PersonaStatus.DRAFT)

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "Try this."},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PERSONA_NOT_REFINABLE"


async def test_non_owner_missing_and_soft_deleted_return_404(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    other_user = User(
        email=f"other-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()
    other_persona, _ = await _make_persona(db_session, other_user)
    deleted_persona, _ = await _make_persona(db_session, test_user, deleted=True)

    for persona_id in [other_persona.id, uuid.uuid4(), deleted_persona.id]:
        response = await client.post(
            f"/api/v1/personas/{persona_id}/refine",
            json={"message": "Try this."},
            headers=auth_headers,
        )
        assert response.status_code == 404


async def test_empty_message_after_sanitize_returns_422(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    persona, _session = await _make_persona(db_session, test_user)

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "   "},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMPTY_PROMPT"


async def test_free_user_with_refine_used_returns_403(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
) -> None:
    test_user.refine_used = True
    await db_session.commit()
    persona, _session = await _make_persona(db_session, test_user)

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "Try this."},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REFINE_LIMIT_REACHED"


async def test_delay_raising_returns_error_sse(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
    mocker,
) -> None:
    persona, _session = await _make_persona(db_session, test_user)
    _patch_relay_redis(mocker, [])
    mocker.patch(
        "app.api.endpoints.personas.refine_persona.delay",
        side_effect=RuntimeError("broker down"),
    )

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "Try this."},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code": "QUEUE_UNAVAILABLE"' in response.text
    assert "event: start" not in response.text


async def test_relay_subscribes_before_enqueue(
    client,
    db_session: AsyncSession,
    test_user: User,
    auth_headers,
    mocker,
) -> None:
    persona, _session = await _make_persona(db_session, test_user)
    order: list[str] = []
    _patch_relay_redis(mocker, [{"type": "done"}], order)
    _patch_delay(mocker, order)

    response = await client.post(
        f"/api/v1/personas/{persona.id}/refine",
        json={"message": "Try this."},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert order[:2] == ["subscribe", "delay"]


async def test_relay_idle_timeout_resets_after_delivered_event(mocker) -> None:
    _patch_relay_redis(
        mocker,
        [
            {"type": "token", "text": "still working"},
            {"type": "done"},
        ],
    )
    _patch_delay(mocker)
    mocker.patch("app.api.endpoints.personas.REFINE_RELAY_IDLE_TIMEOUT_SECONDS", 10.0)

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter(
                [
                    0.0,  # initial deadline
                    0.0,  # first loop check
                    9.0,  # reset after token delivery
                    11.0,  # second loop check, beyond the original deadline
                    12.0,  # reset after terminal delivery
                ]
            )

        def time(self) -> float:
            return next(self._times)

    mocker.patch("app.api.endpoints.personas.asyncio.get_running_loop", return_value=FakeLoop())

    chunks = [
        chunk
        async for chunk in _relay_refine(
            "refine-channel",
            uuid.uuid4(),
            uuid.uuid4(),
            "<USER_INPUT>Try this.</USER_INPUT>",
        )
    ]
    event_headers = [chunk.split("\n", maxsplit=1)[0] for chunk in chunks]

    assert event_headers == ["event: start", "event: token", "event: done"]
    assert not any("REFINE_TIMEOUT" in chunk for chunk in chunks)
