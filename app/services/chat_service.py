import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.persona import Persona
from app.schemas.chat import SessionSummary


async def build_session_summaries(
    db: AsyncSession,
    sessions: list[ChatSession],
) -> list[SessionSummary]:
    """
    Batch-build summaries for a page of sessions.
    Total DB round-trips: 3 (sessions already fetched + personas + last messages).
    """
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    persona_ids = list({s.persona_id for s in sessions if s.persona_id})

    persona_map: dict[uuid.UUID, Persona] = {}
    if persona_ids:
        result = await db.execute(select(Persona).where(Persona.id.in_(persona_ids)))
        persona_map = {p.id: p for p in result.scalars().all()}

    msg = ConversationMessage
    rn = (
        func.row_number()
        .over(
            partition_by=msg.session_id,
            order_by=msg.created_at.desc(),
        )
        .label("rn")
    )

    subq = select(msg.session_id, msg.content, rn).where(msg.session_id.in_(session_ids)).subquery()

    last_msg_result = await db.execute(
        select(subq.c.session_id, subq.c.content).where(subq.c.rn == 1)
    )
    preview_map = {
        row.session_id: row.content[:100] if row.content else None for row in last_msg_result.all()
    }

    summaries = []
    for session in sessions:
        persona = persona_map.get(session.persona_id)
        summaries.append(
            SessionSummary(
                session_id=session.id,
                persona_id=session.persona_id,
                persona_name=persona.name if persona else None,
                last_message_preview=preview_map.get(session.id),
                last_message_at=session.last_message_at,
                status=session.status,
            )
        )
    return summaries
