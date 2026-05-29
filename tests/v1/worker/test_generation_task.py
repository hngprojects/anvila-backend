import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import MessageRole, PersonaStatus, SessionStatus
from app.models.persona import Persona
from app.models.user import User
from app.services.llm.types import LLMResponse
from app.worker.tasks.generation import GENERATION_SYSTEM_PROMPT, _NoRetry, _run_generation


def _llm_response(content: str, tokens: int = 100) -> LLMResponse:
    return LLMResponse(
        content=content,
        input_tokens=tokens // 2,
        output_tokens=tokens // 2,
        total_tokens=tokens,
        model="gemini-2.0-flash",
    )


def _generation_payload() -> dict:
    return {
        "type": "generation",
        "persona_name": "Lighthouse",
        "category": "support",
        "short_description": "Tier-1 SaaS support agent",
        "suggested_skills": ["ticket-triage", "empathy-writer"],
        "files": {
            "identity_md": "# Identity\n\nbody",
            "soul_md": "# Soul\n\nbody",
            "dna_md": "# DNA\n\nbody",
            "overview_md": "# Overview\n\nbody",
            "heartbeat_md": "# Heartbeat\n\nbody",
        },
    }


def _clarification_payload(questions: list[dict] | None = None) -> dict:
    """Default clarification payload with 5 compliant questions.

    Each question has id, question text, options, and allow_custom; tests can
    override to assert boundary conditions.
    """
    return {
        "type": "clarification",
        "questions": questions
        if questions is not None
        else [
            {
                "id": "persona_name",
                "question": "What name?",
                "options": ["Suggest one for me", "I'll provide a custom name"],
                "allow_custom": True,
            },
            {
                "id": "personality",
                "question": "What personality?",
                "options": ["Professional", "Friendly", "Direct"],
                "allow_custom": True,
            },
            {
                "id": "behavior",
                "question": "How should it behave?",
                "options": ["Proactive", "Concise", "Collaborative"],
                "allow_custom": True,
            },
            {
                "id": "audience",
                "question": "Who is the audience?",
                "options": ["Internal team", "External customers", "Executives"],
                "allow_custom": True,
            },
            {
                "id": "output",
                "question": "What does it output?",
                "options": ["Markdown guidance", "Structured tasks", "Reports"],
                "allow_custom": True,
            },
        ],
    }


def _valid_clarification_questions() -> list[dict]:
    return [question.copy() for question in _clarification_payload()["questions"]]


def _patch_redis(mocker) -> MagicMock:
    """Patch Redis.from_url so the task uses an in-memory fake. The fake's
    pubsub returns a default object whose get_message never produces a
    continue message — overridable per-test."""
    fake_pubsub = AsyncMock()
    fake_pubsub.subscribe = AsyncMock()
    fake_pubsub.unsubscribe = AsyncMock()
    fake_pubsub.aclose = AsyncMock()
    fake_pubsub.get_message = AsyncMock(return_value=None)
    fake_pubsub.__aenter__.return_value = fake_pubsub
    fake_pubsub.__aexit__.return_value = None

    fake_client = MagicMock()
    fake_client.pubsub = MagicMock(return_value=fake_pubsub)
    fake_client.publish = AsyncMock(return_value=1)
    fake_client.delete = AsyncMock(return_value=1)
    fake_client.aclose = AsyncMock()

    mocker.patch(
        "app.worker.tasks.generation.Redis.from_url",
        return_value=fake_client,
    )
    return fake_client


@pytest.fixture()
def fake_adapter(mocker):
    adapter = MagicMock()
    adapter.generate = AsyncMock()
    mocker.patch(
        "app.services.llm.factory.get_llm_adapter",
        return_value=adapter,
    )
    return adapter


@pytest.fixture(autouse=True)
def fake_match_skills(mocker):
    matcher = AsyncMock(return_value=[])
    mocker.patch("app.services.skill_matcher.match_skills", matcher)
    return matcher


@pytest.fixture()
async def persona_and_session(
    db_session: AsyncSession, test_user: User
) -> tuple[Persona, ChatSession]:
    persona = Persona(
        user_id=test_user.id,
        name="draft",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        category="development",
        description_summary="",
        visibility="public",
        status="draft",
    )
    db_session.add(persona)
    await db_session.flush()
    session = ChatSession(persona_id=persona.id, user_id=test_user.id)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(persona)
    await db_session.refresh(session)
    return persona, session


async def test_happy_path_clarification_then_generation_then_skills_then_readme(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    continue_payload = json.dumps({"type": "continue", "session_id": str(session.id)}).encode()
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={"type": "message", "data": continue_payload}
    )

    fake_adapter.generate.side_effect = [
        _llm_response(json.dumps(_clarification_payload())),
        _llm_response(json.dumps(_generation_payload())),
    ]

    await _run_generation(
        str(persona.id), str(session.id), "<USER_INPUT>build x</USER_INPUT>", None
    )

    await db_session.refresh(persona)
    await db_session.refresh(session)
    assert persona.status == PersonaStatus.GENERATED
    assert session.status == SessionStatus.COMPLETE
    assert persona.name == "Lighthouse"
    assert persona.identity_md is not None
    assert persona.readme_md is not None
    assert "# Lighthouse" in persona.readme_md
    messages = (
        await db_session.execute(
            select(ConversationMessage).where(ConversationMessage.session_id == session.id)
        )
    ).scalars()
    saved_message = messages.one()
    assert saved_message.role == MessageRole.ASSISTANT
    assert json.loads(saved_message.content) == _clarification_payload()["questions"]
    redis_client.publish.assert_not_awaited()


async def test_invalid_json_marks_failed_with_invalid_llm_response(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    _patch_redis(mocker)
    fake_adapter.generate.return_value = _llm_response("not json at all")

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "INVALID_LLM_RESPONSE"


async def test_valid_json_non_object_marks_failed_with_invalid_llm_response(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    _patch_redis(mocker)
    fake_adapter.generate.return_value = _llm_response("[]")

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "INVALID_LLM_RESPONSE"


async def test_match_skills_not_implemented_is_swallowed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    fake_match_skills,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    _patch_redis(mocker)
    fake_adapter.generate.return_value = _llm_response(json.dumps(_generation_payload()))
    fake_match_skills.side_effect = NotImplementedError

    await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.GENERATED
    assert persona.readme_md is not None
    assert "_No skills attached._" in persona.readme_md


async def test_clarification_timeout_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    # get_message never yields a message; we must avoid wall-clock 5min wait.
    # Patch the timeout constant to 0 so the wait loop exits immediately.
    mocker.patch("app.worker.tasks.generation.CLARIFICATION_TIMEOUT_SECONDS", 0.0)
    redis_client.pubsub.return_value.get_message = AsyncMock(return_value=None)

    fake_adapter.generate.return_value = _llm_response(json.dumps(_clarification_payload()))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "CLARIFICATION_TIMEOUT"


async def test_max_rounds_without_generation_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    # With <= MAX_CLARIFICATION_ROUNDS (=5), the loop exits via while-else
    # only when round > 5 — i.e. when the user has answered the 5th round
    # and the task has yet to be told to continue. The 6th LLM call is
    # what would happen on round 6, but the loop never runs at round=6.
    session.clarification_round = 6
    await db_session.commit()
    _patch_redis(mocker)
    fake_adapter.generate.side_effect = AssertionError("should not be called")

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "MAX_ROUNDS_REACHED"


async def test_continue_payload_non_json_is_dropped(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={"type": "message", "data": b"not-json"}
    )
    mocker.patch("app.worker.tasks.generation.CLARIFICATION_TIMEOUT_SECONDS", 0.1)
    fake_adapter.generate.return_value = _llm_response(json.dumps(_clarification_payload()))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.error_code == "CLARIFICATION_TIMEOUT"


async def test_continue_payload_wrong_type_is_dropped(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={"type": "message", "data": b'{"type":"clarification"}'}
    )
    mocker.patch("app.worker.tasks.generation.CLARIFICATION_TIMEOUT_SECONDS", 0.1)
    fake_adapter.generate.return_value = _llm_response(json.dumps(_clarification_payload()))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.error_code == "CLARIFICATION_TIMEOUT"


async def test_continue_payload_wrong_session_id_is_dropped(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={
            "type": "message",
            "data": b'{"type":"continue","session_id":"WRONG-SESSION-ID"}',
        }
    )
    mocker.patch("app.worker.tasks.generation.CLARIFICATION_TIMEOUT_SECONDS", 0.1)
    fake_adapter.generate.return_value = _llm_response(json.dumps(_clarification_payload()))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.error_code == "CLARIFICATION_TIMEOUT"


async def test_continue_payload_correct_session_id_unblocks(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    payload = json.dumps({"type": "continue", "session_id": str(session.id)}).encode()
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={"type": "message", "data": payload}
    )

    fake_adapter.generate.side_effect = [
        _llm_response(json.dumps(_clarification_payload())),
        _llm_response(json.dumps(_generation_payload())),
    ]

    await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.GENERATED


async def test_five_clarification_cycles_then_generation_makes_six_llm_calls(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    payload = json.dumps({"type": "continue", "session_id": str(session.id)}).encode()
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={"type": "message", "data": payload}
    )

    fake_adapter.generate.side_effect = [
        _llm_response(json.dumps(_clarification_payload())) for _ in range(5)
    ] + [_llm_response(json.dumps(_generation_payload()))]

    await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    assert fake_adapter.generate.await_count == 6
    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.GENERATED


async def test_clarification_round_5_drives_one_final_llm_call(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    """The off-by-one fix: with R=5 already set, the loop runs one more time
    and the LLM gets the chance to generate. Under the old `< 5` boundary,
    this would skip directly to MAX_ROUNDS_REACHED without an LLM call."""
    persona, session = persona_and_session
    session.clarification_round = 5
    await db_session.commit()
    _patch_redis(mocker)
    fake_adapter.generate.return_value = _llm_response(json.dumps(_generation_payload()))

    await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    assert fake_adapter.generate.await_count == 1
    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.GENERATED


async def test_continue_payload_non_dict_json_is_dropped(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    """Valid JSON that isn't an object (e.g. an array or bare string) must
    be dropped, not crash on .get()."""
    persona, session = persona_and_session
    redis_client = _patch_redis(mocker)
    redis_client.pubsub.return_value.get_message = AsyncMock(
        return_value={"type": "message", "data": b'["continue"]'}
    )
    mocker.patch("app.worker.tasks.generation.CLARIFICATION_TIMEOUT_SECONDS", 0.1)
    fake_adapter.generate.return_value = _llm_response(json.dumps(_clarification_payload()))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.error_code == "CLARIFICATION_TIMEOUT"


async def test_terminal_state_short_circuits_without_llm_call(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    persona.status = PersonaStatus.GENERATED
    persona.readme_md = "preserved readme"
    await db_session.commit()
    _patch_redis(mocker)
    fake_adapter.generate.side_effect = AssertionError("should not be called")

    await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.GENERATED
    assert persona.readme_md == "preserved readme"
    fake_adapter.generate.assert_not_called()


async def test_generation_missing_required_field_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    _patch_redis(mocker)
    payload = _generation_payload()
    del payload["files"]["soul_md"]
    fake_adapter.generate.return_value = _llm_response(json.dumps(payload))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "INVALID_LLM_RESPONSE"


async def test_invalid_category_marks_failed_with_invalid_llm_response(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    _patch_redis(mocker)
    payload = _generation_payload()
    payload["category"] = "unicorn"
    fake_adapter.generate.return_value = _llm_response(json.dumps(payload))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "INVALID_LLM_RESPONSE"


async def _assert_invalid_clarification_payload(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session: tuple[Persona, ChatSession],
    payload: dict,
    redis_client: MagicMock,
) -> None:
    """Assert validator rejection keeps malformed clarification payloads out."""
    persona, session = persona_and_session
    mocker.patch("app.worker.tasks.generation.CLARIFICATION_TIMEOUT_SECONDS", 0.0)
    fake_adapter.generate.return_value = _llm_response(json.dumps(payload))

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "INVALID_LLM_RESPONSE"

    assistant_messages = (
        (
            await db_session.execute(
                select(ConversationMessage).where(
                    ConversationMessage.session_id == session.id,
                    ConversationMessage.role == MessageRole.ASSISTANT,
                )
            )
        )
        .scalars()
        .all()
    )
    assert assistant_messages == []

    publish_calls = redis_client.publish.await_args_list
    assert any("INVALID_LLM_RESPONSE" in str(call) for call in publish_calls), (
        f"expected INVALID_LLM_RESPONSE publish; got {publish_calls!r}"
    )


async def test_clarification_with_fewer_than_5_questions_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _clarification_payload()["questions"][:4]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_with_more_than_8_questions_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = [
        {
            "id": f"field_{index}",
            "question": f"Question {index}?",
            "options": ["Option A", "Option B"],
            "allow_custom": True,
        }
        for index in range(9)
    ]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_with_non_list_questions_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        {"type": "clarification", "questions": "abc"},
        redis_client,
    )


async def test_clarification_missing_questions_key_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        {"type": "clarification"},
        redis_client,
    )


async def test_clarification_question_missing_id_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    payload = _clarification_payload()
    del payload["questions"][0]["id"]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        payload,
        redis_client,
    )


async def test_clarification_question_missing_question_text_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    payload = _clarification_payload()
    del payload["questions"][0]["question"]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        payload,
        redis_client,
    )


async def test_clarification_question_id_not_snake_case_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    questions[0]["id"] = "PersonaName"
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_question_missing_options_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    del questions[0]["options"]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_question_options_too_few_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    questions[0]["options"] = ["only one"]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_question_options_too_many_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    questions[0]["options"] = ["one", "two", "three", "four", "five"]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_question_options_contains_empty_string_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    questions[0]["options"] = ["valid", ""]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_question_missing_allow_custom_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    del questions[0]["allow_custom"]
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_question_allow_custom_false_marks_failed(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    questions = _valid_clarification_questions()
    questions[0]["allow_custom"] = False
    redis_client = _patch_redis(mocker)

    await _assert_invalid_clarification_payload(
        mocker,
        db_session,
        fake_adapter,
        persona_and_session,
        _clarification_payload(questions),
        redis_client,
    )


async def test_clarification_validator_does_not_increment_clarification_rounds(
    mocker,
    db_session: AsyncSession,
    fake_adapter,
    persona_and_session,
) -> None:
    persona, session = persona_and_session
    persona.clarification_rounds = 2
    await db_session.commit()
    _patch_redis(mocker)
    fake_adapter.generate.return_value = _llm_response(
        json.dumps(_clarification_payload(_clarification_payload()["questions"][:4]))
    )

    with pytest.raises(_NoRetry):
        await _run_generation(str(persona.id), str(session.id), "<USER_INPUT>x</USER_INPUT>", None)

    await db_session.refresh(persona)
    assert persona.status == PersonaStatus.FAILED
    assert persona.error_code == "INVALID_LLM_RESPONSE"
    assert persona.clarification_rounds == 2


def test_generation_system_prompt_requires_5_to_8_questions() -> None:
    prompt = GENERATION_SYSTEM_PROMPT

    assert "Ask 5 to 8 questions per round." in prompt
    assert '"options" list of 2 to 4 short non-empty choices' in prompt
    assert 'snake_case "id"' in prompt
    assert '"question" text' in prompt
    assert "allow_custom" in prompt

    prompt_lower = prompt.lower()
    assert "persona name" in prompt_lower
    assert "personality" in prompt_lower
    assert "behavior" in prompt_lower
    assert "role" in prompt_lower
    assert "domain" in prompt_lower or "purpose" in prompt_lower
    assert "audience" in prompt_lower
    assert "skills" in prompt_lower or "tools" in prompt_lower
    assert "output" in prompt_lower or "task expectations" in prompt_lower
