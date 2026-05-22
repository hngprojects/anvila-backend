import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, CursorPaginationParams, DBSession
from app.core.paginator import CursorMeta, cursor_paginate
from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.persona import Persona
from app.schemas.chat import MessageOut, SessionSummary
from app.schemas.shared import ApiResponse
from app.services.chat_service import build_session_summaries

router = APIRouter(tags=["chat"])


@router.get("/chat/sessions", response_model=ApiResponse[list[SessionSummary]])
async def list_all_sessions(
    user: CurrentUser,
    db: DBSession,
    params: CursorPaginationParams,
):
    """
    All chat sessions for the current user across all personas.
    Sorted by most recent activity — mirrors a ChatGPT-style sidebar.
    Use cursor for pagination: pass the session_id of the last item received.
    """
    query = (
        select(ChatSession)
        .join(Persona, Persona.id == ChatSession.persona_id)
        .where(
            Persona.user_id == user.id,
            ChatSession.deleted_at == None,  # noqa
        )
    )
    sessions, meta = await cursor_paginate(
        db, query, params, ChatSession, "last_message_at", descending=True
    )
    summaries = await build_session_summaries(db, sessions)

    return ApiResponse[list[SessionSummary]](
        message="Chat sessions retrieved successfully",
        data=summaries,
        meta=meta.model_dump(),
    )


@router.get("/personas/{persona_id}/messages", response_model=ApiResponse[list[MessageOut]])
async def list_session_messages(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    params: CursorPaginationParams,
):
    """
    Messages for a specific session. Ordered oldest-first (chat scroll behaviour).
    Use cursor for pagination: pass the message id of the last item received.
    Returns empty list if session has no messages — not a 404.
    """
    # Verify ownership chain: persona → session → user
    persona = await db.get(Persona, persona_id)
    if not persona or persona.user_id != user.id:
        raise HTTPException(status_code=404, detail="Persona not found")

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.persona_id == persona_id,
            ChatSession.deleted_at == None,  # noqa
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return ApiResponse[list[MessageOut]](
            message="Messages successfully retrieved",
            data=[],
            meta=CursorMeta(size=params.size, has_more=False, next_cursor=None).model_dump(),
        )
    query = select(ConversationMessage).where(
        ConversationMessage.session_id == session.id,
    )
    messages, meta = await cursor_paginate(
        db, query, params, ConversationMessage, "created_at", descending=False
    )
    return ApiResponse[list[MessageOut]](
        message="Messages successfully retrieved",
        data=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                round_number=m.round_number,
                created_at=m.created_at,
            )
            for m in messages
        ],
        meta=meta.model_dump(),
    )


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
):
    """
    Soft delete a chat session and all its messages.
    Does not affect the persona record or any published GitHub repo.
    Celery Beat hard-deletes after 30 days.
    """
    session = await db.get(ChatSession, session_id)
    if not session or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")

    persona = await db.get(Persona, session.persona_id)
    if not persona or persona.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    now = datetime.now(UTC)

    session.deleted_at = now
    await db.commit()
