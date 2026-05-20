import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.enums import UserPlan, UserProvider
from app.models.persona import Persona
from app.models.user import User
from app.services.context_manager import ContextManager


@pytest.fixture()
async def session_with_owner(db_session: AsyncSession) -> ChatSession:
    user = User(
        email=f"ctx-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    persona = Persona(
        user_id=user.id,
        name="ctx-fixture",
        slug=f"ctx-{uuid.uuid4().hex[:8]}",
        category="development",
        description_summary="",
        visibility="public",
        status="draft",
    )
    db_session.add(persona)
    await db_session.flush()
    session = ChatSession(persona_id=persona.id, user_id=user.id)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def test_compress_initializes_fresh_user_intent_block(
    session_with_owner: ChatSession, db_session: AsyncSession
) -> None:
    answers = [{"id": "role", "answer": "tier-1 support agent"}]
    result = await ContextManager().compress(session_with_owner, answers, db_session)

    assert result.startswith("User intent:")
    assert "Q: role" in result
    assert "A: tier-1 support agent" in result

    await db_session.refresh(session_with_owner)
    assert session_with_owner.compressed_context == result


async def test_compress_appends_when_prior_context_exists(
    session_with_owner: ChatSession, db_session: AsyncSession
) -> None:
    session_with_owner.compressed_context = "User intent:\nQ: role\nA: support"
    await db_session.commit()

    answers = [{"id": "audience", "answer": "smb saas"}]
    result = await ContextManager().compress(session_with_owner, answers, db_session)

    assert "Q: role" in result
    assert "A: support" in result
    assert "Q: audience" in result
    assert "A: smb saas" in result
    assert result.startswith("User intent:")


async def test_compress_commits_so_other_sessions_see_update(
    session_with_owner: ChatSession, db_session: AsyncSession
) -> None:
    await ContextManager().compress(
        session_with_owner,
        [{"id": "x", "answer": "y"}],
        db_session,
    )

    refreshed = await db_session.get(ChatSession, session_with_owner.id)
    assert refreshed is not None
    assert refreshed.compressed_context is not None
    assert "Q: x" in refreshed.compressed_context


def test_build_followup_prompt_includes_system_context_and_answers() -> None:
    session = SimpleNamespace(compressed_context="User intent:\nQ: role\nA: support agent")
    prompt = ContextManager().build_followup_prompt(
        session,
        [{"id": "audience", "answer": "smb saas"}],
        "SYSTEM_PROMPT_BODY",
    )

    assert "SYSTEM_PROMPT_BODY" in prompt
    assert "CONTEXT SO FAR:" in prompt
    assert "User intent:" in prompt
    assert "LATEST ANSWERS:" in prompt
    assert "Q: audience" in prompt
    assert "A: smb saas" in prompt
    assert "Continue generation" in prompt


def test_build_followup_prompt_omits_raw_message_history() -> None:
    session = SimpleNamespace(compressed_context="User intent:\nQ: role\nA: x")
    prompt = ContextManager().build_followup_prompt(
        session,
        [{"id": "x", "answer": "y"}],
        "SYS",
    )

    # Implementation must use compressed_context, not iterate ConversationMessage rows.
    assert "ConversationMessage" not in prompt
    assert "messages" not in prompt.lower() or "messages" in "LATEST ANSWERS:".lower()
