import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import MessageRole, PersonaCategory, PersonaStatus, SkillSourceRegistry
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.models.user import User
from app.services.llm.types import LLMResponse, LLMStreamChunk
from app.worker.tasks.refine import ASSISTANT_GENERATION_MARKER, _NoRetry, _run_refine


def _llm_usage(tokens: int = 40) -> LLMResponse:
    return LLMResponse(
        content="",
        input_tokens=tokens // 2,
        output_tokens=tokens // 2,
        total_tokens=tokens,
        model="gemini-2.0-flash",
    )


async def _async_chunks(parts: list[str], tokens: int = 40):
    for part in parts:
        yield LLMStreamChunk(text=part)
    yield LLMStreamChunk(text="", usage=_llm_usage(tokens))


def _generation_payload(name: str = "Refined Lighthouse") -> dict:
    return {
        "type": "generation",
        "persona_name": name,
        "category": "support",
        "short_description": "Refined SaaS support agent",
        "suggested_skills": ["ticket-triage"],
        "files": {
            "identity_md": "# Identity\n\nrefined",
            "soul_md": "# Soul\n\nrefined",
            "dna_md": "# DNA\n\nrefined",
            "overview_md": "# Overview\n\nrefined",
            "heartbeat_md": "# Heartbeat\n\nrefined",
        },
    }


def _patch_redis(mocker) -> MagicMock:
    fake_client = MagicMock()
    fake_client.events = []

    async def _publish(channel: str, payload: str) -> int:
        fake_client.events.append((channel, json.loads(payload)))
        return 1

    fake_client.publish = AsyncMock(side_effect=_publish)
    fake_client.aclose = AsyncMock()
    mocker.patch("app.worker.tasks.refine.Redis.from_url", return_value=fake_client)
    return fake_client


def _patch_adapter(mocker, parts: list[str]) -> MagicMock:
    adapter = MagicMock()
    adapter.stream = MagicMock(return_value=_async_chunks(parts))
    mocker.patch("app.services.llm.factory.get_llm_adapter", return_value=adapter)
    return adapter


@pytest.fixture(autouse=True)
def fake_match_skills(mocker):
    matcher = AsyncMock(return_value=[])
    mocker.patch("app.services.skill_matcher.match_skills", matcher)
    return matcher


async def _make_persona_with_session(
    db_session: AsyncSession,
    user: User,
    *,
    status: PersonaStatus = PersonaStatus.GENERATED,
) -> tuple[Persona, ChatSession]:
    persona = Persona(
        user_id=user.id,
        name="Original Lighthouse",
        slug=f"refine-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.SUPPORT,
        description_summary="Original support agent",
        visibility="public",
        status=status,
        identity_md="# Identity\n\noriginal",
        soul_md="# Soul\n\noriginal",
        dna_md="# DNA\n\noriginal",
        overview_md="# Overview\n\noriginal",
        heartbeat_md="# Heartbeat\n\noriginal",
        readme_md="# Original",
    )
    db_session.add(persona)
    await db_session.flush()
    session = ChatSession(persona_id=persona.id, user_id=user.id)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(persona)
    await db_session.refresh(session)
    return persona, session


async def _add_current_user_message(
    db_session: AsyncSession,
    persona: Persona,
    session: ChatSession,
    content: str,
) -> None:
    db_session.add(
        ConversationMessage(
            session_id=session.id,
            persona_id=persona.id,
            role=MessageRole.USER,
            content=content,
            round_number=1,
        )
    )
    await db_session.commit()


async def _assistant_messages(
    db_session: AsyncSession,
    session: ChatSession,
) -> list[ConversationMessage]:
    result = await db_session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.session_id == session.id,
            ConversationMessage.role == MessageRole.ASSISTANT,
        )
        .order_by(ConversationMessage.created_at)
    )
    return list(result.scalars().all())


async def test_text_turn_streams_tokens_persists_assistant_and_does_not_consume_refine(
    mocker,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    persona, session = await _make_persona_with_session(db_session, test_user)
    user_message = "<USER_INPUT>Should this persona support escalations?</USER_INPUT>"
    await _add_current_user_message(db_session, persona, session, user_message)
    redis_client = _patch_redis(mocker)
    _patch_adapter(mocker, ["Yes, ", "add escalation guidance."])

    await _run_refine(str(persona.id), str(session.id), "refine-channel", user_message)

    await db_session.refresh(persona)
    await db_session.refresh(test_user)
    assert persona.status == PersonaStatus.GENERATED
    assert test_user.refine_used is False

    event_types = [payload["type"] for _, payload in redis_client.events]
    assert event_types == ["token", "token", "done"]
    assert redis_client.events[0][1] == {"type": "token", "text": "Yes, "}
    assert redis_client.events[1][1] == {
        "type": "token",
        "text": "add escalation guidance.",
    }
    assert redis_client.events[2][1] == {"type": "done"}

    messages = await _assistant_messages(db_session, session)
    assert len(messages) == 1
    assert messages[0].content == "Yes, add escalation guidance."


async def test_publish_failure_after_commit_does_not_retry_or_duplicate(
    mocker,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    persona, session = await _make_persona_with_session(db_session, test_user)
    user_message = "<USER_INPUT>Should this persona support escalations?</USER_INPUT>"
    await _add_current_user_message(db_session, persona, session, user_message)
    redis_client = _patch_redis(mocker)
    _patch_adapter(mocker, ["Yes, add escalation guidance."])

    async def _publish(channel: str, payload: str) -> int:
        event = json.loads(payload)
        redis_client.events.append((channel, event))
        if event["type"] == "done":
            raise RuntimeError("redis publish failed")
        return 1

    redis_client.publish = AsyncMock(side_effect=_publish)

    await _run_refine(str(persona.id), str(session.id), "refine-channel", user_message)

    await db_session.refresh(persona)
    await db_session.refresh(test_user)
    assert persona.tokens_used == 40
    assert test_user.total_tokens_used == 40
    assert test_user.refine_used is False

    event_types = [payload["type"] for _, payload in redis_client.events]
    assert event_types == ["token", "done"]

    messages = await _assistant_messages(db_session, session)
    assert len(messages) == 1
    assert messages[0].content == "Yes, add escalation guidance."


async def test_generation_turn_replaces_skills_sets_refine_used_and_drops_published_to_generated(
    mocker,
    db_session: AsyncSession,
    test_user: User,
    fake_match_skills,
) -> None:
    persona, session = await _make_persona_with_session(
        db_session,
        test_user,
        status=PersonaStatus.PUBLISHED,
    )
    user_message = "<USER_INPUT>Make it more empathetic.</USER_INPUT>"
    await _add_current_user_message(db_session, persona, session, user_message)

    old_skill = Skill(
        name="Old Skill",
        slug=f"old-skill-{uuid.uuid4().hex[:8]}",
        description="Old skill",
        content="# Old",
        category=PersonaCategory.SUPPORT,
        tags=["old"],
        source_registry=SkillSourceRegistry.ANVILA,
    )
    new_skill = Skill(
        name="Ticket Triage",
        slug=f"ticket-triage-{uuid.uuid4().hex[:8]}",
        description="Triage support tickets",
        content="# Ticket Triage",
        category=PersonaCategory.SUPPORT,
        tags=["support"],
        source_registry=SkillSourceRegistry.ANVILA,
    )
    db_session.add_all([old_skill, new_skill])
    await db_session.flush()
    db_session.add(PersonaSkill(persona_id=persona.id, skill_id=old_skill.id))
    await db_session.commit()
    fake_match_skills.return_value = [new_skill]

    redis_client = _patch_redis(mocker)
    payload = json.dumps(_generation_payload())
    _patch_adapter(mocker, [payload[:20], payload[20:]])

    await _run_refine(str(persona.id), str(session.id), "refine-channel", user_message)

    await db_session.refresh(persona)
    await db_session.refresh(test_user)
    assert persona.status == PersonaStatus.GENERATED
    assert persona.name == "Refined Lighthouse"
    assert persona.description_summary == "Refined SaaS support agent"
    assert persona.identity_md == "# Identity\n\nrefined"
    assert test_user.refine_used is True

    skill_ids = (
        await db_session.execute(
            select(PersonaSkill.skill_id).where(PersonaSkill.persona_id == persona.id)
        )
    ).scalars()
    assert list(skill_ids) == [new_skill.id]

    event_types = [payload["type"] for _, payload in redis_client.events]
    assert event_types == [
        "status",
        "file",
        "file",
        "file",
        "file",
        "file",
        "skills",
        "complete",
    ]
    assert redis_client.events[0][1] == {"type": "status", "state": "regenerating"}
    assert redis_client.events[-2][1]["skills"] == [
        {
            "slug": new_skill.slug,
            "name": "Ticket Triage",
            "description": "Triage support tickets",
            "tags": ["support"],
        }
    ]
    assert redis_client.events[-1][1] == {
        "type": "complete",
        "persona_id": str(persona.id),
        "name": "Refined Lighthouse",
        "category": "support",
        "description": "Refined SaaS support agent",
    }

    messages = await _assistant_messages(db_session, session)
    assert len(messages) == 1
    assert messages[0].content == ASSISTANT_GENERATION_MARKER


async def test_generation_turn_on_generated_persona_stays_generated(
    mocker,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    persona, session = await _make_persona_with_session(db_session, test_user)
    user_message = "<USER_INPUT>Regenerate it with sharper rules.</USER_INPUT>"
    await _add_current_user_message(db_session, persona, session, user_message)
    _patch_redis(mocker)
    _patch_adapter(mocker, [json.dumps(_generation_payload("Sharper Lighthouse"))])

    await _run_refine(str(persona.id), str(session.id), "refine-channel", user_message)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.GENERATED
    assert persona.name == "Sharper Lighthouse"


async def test_malformed_generation_json_publishes_error_and_leaves_prior_state(
    mocker,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    persona, session = await _make_persona_with_session(
        db_session,
        test_user,
        status=PersonaStatus.PUBLISHED,
    )
    user_message = "<USER_INPUT>Regenerate it.</USER_INPUT>"
    await _add_current_user_message(db_session, persona, session, user_message)
    redis_client = _patch_redis(mocker)
    _patch_adapter(mocker, ['{"type":"generation"'])

    with pytest.raises(_NoRetry):
        await _run_refine(str(persona.id), str(session.id), "refine-channel", user_message)

    await db_session.refresh(persona)
    await db_session.refresh(test_user)
    assert persona.status == PersonaStatus.PUBLISHED
    assert persona.error_code is None
    assert test_user.refine_used is False

    event_types = [payload["type"] for _, payload in redis_client.events]
    assert event_types == ["status", "error"]
    assert redis_client.events[-1][1] == {
        "type": "error",
        "code": "INVALID_LLM_RESPONSE",
        "message": "LLM returned malformed generation JSON.",
    }


async def test_discriminator_treats_leading_whitespace_before_object_as_generation(
    mocker,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    persona, session = await _make_persona_with_session(db_session, test_user)
    user_message = "<USER_INPUT>Regenerate with more detail.</USER_INPUT>"
    await _add_current_user_message(db_session, persona, session, user_message)
    redis_client = _patch_redis(mocker)
    _patch_adapter(mocker, [" \n\t", json.dumps(_generation_payload())])

    await _run_refine(str(persona.id), str(session.id), "refine-channel", user_message)

    event_types = [payload["type"] for _, payload in redis_client.events]
    assert event_types[0] == "status"
    assert "token" not in event_types
