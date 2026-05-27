"""Cleanup tasks for expired soft-deleted records."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.persona import Persona
from app.worker.celery_app import celery_app

PURGE_AFTER_DAYS = 30

logger = logging.getLogger(__name__)


def _rowcount(result: CursorResult) -> int:
    return result.rowcount if result.rowcount is not None else 0


async def _purge_soft_deleted() -> dict[str, int]:
    """Permanently remove soft-deleted personas and sessions past the retention window."""
    cutoff = datetime.now(UTC) - timedelta(days=PURGE_AFTER_DAYS)
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            messages_result = await db.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.session_id.in_(
                        select(ChatSession.id).where(ChatSession.deleted_at < cutoff)
                    )
                )
            )
            sessions_result = await db.execute(
                delete(ChatSession).where(ChatSession.deleted_at < cutoff)
            )
            personas_result = await db.execute(delete(Persona).where(Persona.deleted_at < cutoff))
            await db.commit()
    finally:
        await engine.dispose()

    return {
        "messages_deleted": _rowcount(messages_result),
        "sessions_deleted": _rowcount(sessions_result),
        "personas_deleted": _rowcount(personas_result),
    }


@celery_app.task
def purge_soft_deleted() -> dict[str, int]:
    """Run the soft-delete purge task and return deletion counts."""
    result = asyncio.run(_purge_soft_deleted())
    logger.info(
        "purge_soft_deleted complete: messages=%d sessions=%d personas=%d",
        result["messages_deleted"],
        result["sessions_deleted"],
        result["personas_deleted"],
    )
    return result
