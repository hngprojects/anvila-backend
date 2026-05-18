from app.worker.celery_app import celery_app

PURGE_AFTER_DAYS = 30


@celery_app.task
def purge_soft_deleted() -> dict:
    import asyncio
    import logging
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    logger = logging.getLogger(__name__)

    async def _run() -> dict:
        from app.core.config import settings
        from app.models.chat_session import ChatSession
        from app.models.conversation_message import ConversationMessage
        from app.models.persona import Persona

        cutoff = datetime.now(UTC) - timedelta(days=PURGE_AFTER_DAYS)
        engine = create_async_engine(str(settings.DATABASE_URL))
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as db:
            msg_res = await db.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.session_id.in_(
                        select(ChatSession.id).where(ChatSession.deleted_at < cutoff)
                    )
                )
            )
            await db.commit()

            sess_res = await db.execute(
                delete(ChatSession).where(ChatSession.deleted_at < cutoff)
            )
            await db.commit()

            persona_res = await db.execute(
                delete(Persona).where(Persona.deleted_at < cutoff)
            )
            await db.commit()

        await engine.dispose()
        return {
            "messages_deleted": msg_res.rowcount,
            "sessions_deleted": sess_res.rowcount,
            "personas_deleted": persona_res.rowcount,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "purge_soft_deleted complete — messages=%d sessions=%d personas=%d",
            result["messages_deleted"],
            result["sessions_deleted"],
            result["personas_deleted"],
        )
        return result
    except Exception:
        logger.exception("purge_soft_deleted failed")
        return {"messages_deleted": 0, "sessions_deleted": 0, "personas_deleted": 0}
