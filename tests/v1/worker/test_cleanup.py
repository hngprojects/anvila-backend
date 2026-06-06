import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import (
    MessageRole,
    PersonaCategory,
    PersonaStatus,
    PersonaVisibility,
    UserPlan,
    UserProvider,
)
from app.models.persona import Persona
from app.models.user import User
from app.worker.tasks.cleanup import purge_soft_deleted


async def test_purge_soft_deleted_removes_expired_records(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    expired_at = now - timedelta(days=31)
    recent_at = now - timedelta(days=1)

    user = User(
        email=f"cleanup-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    expired_persona = Persona(
        user_id=user.id,
        name="expired",
        slug=f"expired-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="expired persona",
        visibility=PersonaVisibility.PRIVATE,
        status=PersonaStatus.DRAFT,
        deleted_at=expired_at,
    )
    recent_persona = Persona(
        user_id=user.id,
        name="recent",
        slug=f"recent-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="recent persona",
        visibility=PersonaVisibility.PRIVATE,
        status=PersonaStatus.DRAFT,
        deleted_at=recent_at,
    )
    active_persona = Persona(
        user_id=user.id,
        name="active",
        slug=f"active-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="active persona",
        visibility=PersonaVisibility.PRIVATE,
        status=PersonaStatus.DRAFT,
        deleted_at=None,
    )
    personas = [expired_persona, recent_persona, active_persona]
    db_session.add_all(personas)
    await db_session.flush()

    sessions: list[ChatSession] = []
    for persona in personas:
        sessions.extend(
            [
                ChatSession(
                    persona_id=persona.id,
                    user_id=user.id,
                    deleted_at=expired_at,
                ),
                ChatSession(
                    persona_id=persona.id,
                    user_id=user.id,
                    deleted_at=recent_at,
                ),
            ]
        )
    db_session.add_all(sessions)
    await db_session.flush()

    messages = [
        ConversationMessage(
            session_id=session.id,
            persona_id=session.persona_id,
            role=MessageRole.USER,
            content=f"message-{index}",
            round_number=0,
        )
        for index, session in enumerate(sessions)
    ]
    db_session.add_all(messages)
    await db_session.commit()

    result = await asyncio.to_thread(purge_soft_deleted)

    assert result == {
        "messages_deleted": 3,
        "sessions_deleted": 3,
        "personas_deleted": 1,
    }

    remaining_personas = set(await db_session.scalars(select(Persona.id).order_by(Persona.id)))
    assert expired_persona.id not in remaining_personas
    assert recent_persona.id in remaining_personas
    assert active_persona.id in remaining_personas

    remaining_sessions = set(
        await db_session.scalars(select(ChatSession.id).order_by(ChatSession.id))
    )
    assert sessions[0].id not in remaining_sessions
    assert sessions[1].id not in remaining_sessions
    assert sessions[2].id not in remaining_sessions
    assert sessions[3].id in remaining_sessions
    assert sessions[4].id not in remaining_sessions
    assert sessions[5].id in remaining_sessions

    remaining_messages = set(
        await db_session.scalars(select(ConversationMessage.id).order_by(ConversationMessage.id))
    )
    assert messages[0].id not in remaining_messages
    assert messages[1].id not in remaining_messages
    assert messages[2].id not in remaining_messages
    assert messages[3].id in remaining_messages
    assert messages[4].id not in remaining_messages
    assert messages[5].id in remaining_messages
