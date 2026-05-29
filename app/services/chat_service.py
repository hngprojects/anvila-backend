from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.schemas.chat import SessionSummary


async def build_session_summaries(
    db: AsyncSession,
    sessions: list[ChatSession],
) -> list[SessionSummary]:
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    max_dt_subq = (
        select(
            ConversationMessage.session_id,
            func.max(ConversationMessage.created_at).label("max_dt"),
        )
        .where(ConversationMessage.session_id.in_(session_ids))
        .group_by(ConversationMessage.session_id)
        .subquery()
    )

    last_msg_stmt = select(ConversationMessage).join(
        max_dt_subq,
        and_(
            ConversationMessage.session_id == max_dt_subq.c.session_id,
            ConversationMessage.created_at == max_dt_subq.c.max_dt,
        ),
    )
    last_msgs = await db.scalars(last_msg_stmt)
    last_msg_map = {msg.session_id: msg for msg in last_msgs.all()}

    summaries = []
    for session in sessions:
        persona = session.persona
        last_msg = last_msg_map.get(session.id)

        preview = None
        if last_msg and last_msg.content:
            preview = last_msg.content[:120]
            # title = preview[:40] + "…" if len(preview) > 40 else preview
        else:
            pass
            # title = "New Chat"

        summaries.append(
            SessionSummary(
                session_id=session.id,
                persona_id=session.persona_id,
                persona_name=persona.name if persona else "Unknown",
                last_message_preview=preview,
                last_message_at=session.last_message_at,
                status=session.status,
            )
        )

    return summaries
