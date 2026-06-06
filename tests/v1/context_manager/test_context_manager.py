import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import MessageRole, UserPlan, UserProvider
from app.models.persona import Persona
from app.models.user import User
from app.services.clarification_store import serialize_questions, format_questions
from app.services.context_manager import ContextManager


@pytest.fixture()
async def owner(db_session: AsyncSession) -> User:
    user = User(
        email=f"ctx-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture()
async def persona_and_session(owner: User, db_session: AsyncSession) -> tuple[Persona, ChatSession]:
    persona = Persona(
        user_id=owner.id,
        name="ctx-fixture",
        slug=f"ctx-{uuid.uuid4().hex[:8]}",
        category="development",
        description_summary="",
        visibility="public",
        status="draft",
    )
    db_session.add(persona)
    await db_session.flush()

    session = ChatSession(persona_id=persona.id, user_id=owner.id)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(persona)
    await db_session.refresh(session)
    return persona, session


def _add_question_row(
    persona: Persona,
    session: ChatSession,
    round_number: int,
    raw_questions: list[dict],
) -> ConversationMessage:
    """Build a ConversationMessage as store_questions() would — not yet added to db."""
    formatted = format_questions(raw_questions)
    return ConversationMessage(
        session_id=session.id,
        persona_id=persona.id,
        role=MessageRole.ASSISTANT,
        content=serialize_questions(formatted),
        round_number=round_number,
    )


async def test_compress_upserts_answer_into_question_row(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    raw_questions = [
        {
            "id": "role",
            "question": "What is the persona's primary role?",
            "options": ["Support", "Sales"],
        },
    ]
    msg = _add_question_row(persona, session, round_number=1, raw_questions=raw_questions)
    db_session.add(msg)
    await db_session.commit()

    await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "role", "answer": "tier-1 support agent"}],
        db=db_session,
    )

    await db_session.refresh(msg)
    stored = json.loads(msg.content)
    answered = {q["id"]: q["answer"] for q in stored["questions"]}
    assert answered["role"] == "tier-1 support agent"


async def test_compress_rebuilds_context_with_full_question_text(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    raw_questions = [
        {
            "id": "role",
            "question": "What is the persona's primary role?",
            "options": ["Support", "Sales"],
        },
    ]
    msg = _add_question_row(persona, session, round_number=1, raw_questions=raw_questions)
    db_session.add(msg)
    await db_session.commit()

    result = await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "role", "answer": "tier-1 support agent"}],
        db=db_session,
    )

    # Must use full question text, not the id
    assert "What is the persona's primary role?" in result
    assert "tier-1 support agent" in result
    assert "Q: role" not in result  # old format must not appear


async def test_compress_persists_context_on_session(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    raw_questions = [
        {"id": "audience", "question": "Who is the target audience?", "options": ["B2B", "B2C"]},
    ]
    msg = _add_question_row(persona, session, round_number=1, raw_questions=raw_questions)
    db_session.add(msg)
    await db_session.commit()

    result = await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "audience", "answer": "smb saas"}],
        db=db_session,
    )

    await db_session.refresh(session)
    assert session.compressed_context == result
    assert session.compressed_context is not None
    assert "Who is the target audience?" in session.compressed_context
    assert "smb saas" in session.compressed_context


async def test_compress_accumulates_multiple_rounds(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    round_1 = _add_question_row(
        persona,
        session,
        round_number=1,
        raw_questions=[
            {
                "id": "role",
                "question": "What is the persona's primary role?",
                "options": ["Support"],
            },
        ],
    )
    round_2 = _add_question_row(
        persona,
        session,
        round_number=2,
        raw_questions=[
            {
                "id": "tone",
                "question": "What tone should the persona use?",
                "options": ["Formal", "Casual"],
            },
        ],
    )
    db_session.add(round_1)
    db_session.add(round_2)
    await db_session.commit()

    # Compress round 1
    await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "role", "answer": "support agent"}],
        db=db_session,
    )
    # Compress round 2
    result = await ContextManager().compress(
        persona_id=persona.id,
        round_number=2,
        answers=[{"id": "tone", "answer": "formal"}],
        db=db_session,
    )

    assert "What is the persona's primary role?" in result
    assert "support agent" in result
    assert "What tone should the persona use?" in result
    assert "formal" in result


async def test_compress_skips_unanswered_questions_in_context(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    raw_questions = [
        {"id": "role", "question": "What is the persona's primary role?", "options": ["Support"]},
        {"id": "tone", "question": "What tone should the persona use?", "options": ["Formal"]},
    ]
    msg = _add_question_row(persona, session, round_number=1, raw_questions=raw_questions)
    db_session.add(msg)
    await db_session.commit()

    # Only answer one question
    result = await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "role", "answer": "support agent"}],
        db=db_session,
    )

    assert "What is the persona's primary role?" in result
    assert "support agent" in result
    # Unanswered question should not appear in context
    assert "What tone should the persona use?" not in result


async def test_compress_returns_empty_string_when_no_answers_matched(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    raw_questions = [
        {"id": "role", "question": "What is the persona's primary role?", "options": ["Support"]},
    ]
    msg = _add_question_row(persona, session, round_number=1, raw_questions=raw_questions)
    db_session.add(msg)
    await db_session.commit()

    # Answer with a non-existent id
    result = await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "nonexistent", "answer": "something"}],
        db=db_session,
    )

    # No answered questions — context should be empty
    assert result == ""


async def test_compress_handles_missing_question_row_gracefully(
    persona_and_session: tuple[Persona, ChatSession],
    db_session: AsyncSession,
) -> None:
    persona, session = persona_and_session

    # No ConversationMessage row exists for round 1
    result = await ContextManager().compress(
        persona_id=persona.id,
        round_number=1,
        answers=[{"id": "role", "answer": "support"}],
        db=db_session,
    )

    # Should not raise — returns empty context
    assert result == ""


def test_build_followup_prompt_includes_system_prompt_and_context() -> None:
    compressed = "Round 1:\nQ: What is the persona's primary role?\nA: support agent"
    prompt = ContextManager().build_followup_prompt(
        compressed_context=compressed,
        system_prompt="SYSTEM_PROMPT_BODY",
    )
    assert "SYSTEM_PROMPT_BODY" in prompt
    assert "CONTEXT SO FAR:" in prompt
    assert "What is the persona's primary role?" in prompt
    assert "support agent" in prompt
    assert "Continue generation" in prompt


def test_build_followup_prompt_handles_empty_context() -> None:
    prompt = ContextManager().build_followup_prompt(
        compressed_context="",
        system_prompt="SYSTEM_PROMPT_BODY",
    )
    assert "SYSTEM_PROMPT_BODY" in prompt
    assert "CONTEXT SO FAR:" in prompt
    assert "Continue generation" in prompt


def test_build_followup_prompt_does_not_include_raw_ids() -> None:
    """Prompt must never expose raw question IDs — only full text passed in via compressed_context."""
    compressed = "Round 1:\nQ: What is the persona's primary role?\nA: support agent"
    prompt = ContextManager().build_followup_prompt(
        compressed_context=compressed,
        system_prompt="SYS",
    )
    # The old format used Q: {id} — make sure raw IDs are not leaking from the method itself
    assert "Q: role" not in prompt
    assert "LATEST ANSWERS:" not in prompt  # old signature artifact
