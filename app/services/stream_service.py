import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.conversation_message import ConversationMessage
from app.models.enums import MessageRole, PersonaStatus
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.5

# Timeout (seconds) to wait for a ConversationMessage to appear after
# NEEDS_CLARIFICATION status is detected. The Celery task commits the
# persona status and the message in the same db.commit(), but the poller
# may read the new status in the same cycle before the commit propagates
# (read-your-writes lag on async connections). We retry for up to this
# many seconds before giving up and waiting for the next poll cycle.
CLARIFICATION_MSG_WAIT = 3.0

FILE_COLUMNS = [
    "identity_md",
    "soul_md",
    "dna_md",
    "overview_md",
    "heartbeat_md",
    "readme_md",
]

_DONE = object()


def _sse(event: str, data: dict) -> str:
    """Format a server-sent event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _get_skills(persona_id: uuid.UUID, db: AsyncSession) -> list[dict]:
    """Fetch full skill objects attached to a persona."""
    result = await db.execute(
        select(Skill)
        .join(PersonaSkill, PersonaSkill.skill_id == Skill.id)
        .where(PersonaSkill.persona_id == persona_id)
    )
    return [
        {
            "slug": s.slug,
            "name": s.name,
            "description": s.description,
            "tags": s.tags or [],
        }
        for s in result.scalars().all()
    ]


async def _fetch_clarification_message(
    persona_id: uuid.UUID,
    round_num: int,
    db: AsyncSession,
) -> list | None:
    """
    Fetch the clarification questions for a given round from the DB.

    Retries for up to CLARIFICATION_MSG_WAIT seconds to handle the small
    window where the Celery task has committed the persona status but the
    ConversationMessage row is not yet visible to this connection.

    Returns the parsed questions list, or None if the message was not found
    within the retry window (caller should wait for the next poll cycle).
    """
    deadline = asyncio.get_running_loop().time() + CLARIFICATION_MSG_WAIT
    while asyncio.get_running_loop().time() < deadline:
        result = await db.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.persona_id == persona_id,
                ConversationMessage.role == MessageRole.ASSISTANT,
                ConversationMessage.round_number == round_num,
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        msg = result.scalar_one_or_none()
        if msg is not None:
            try:
                return json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                return []
        await asyncio.sleep(0.3)
    return None


async def _poll_db(
    persona_id: uuid.UUID,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
) -> None:
    """
    Single source of truth for all SSE events.

    Uses NullPool so it never competes with the request-scoped session.

    Emits (in order as they become available):
      file          — once per column, as soon as non-null.
      skills        — once, as soon as PersonaSkill rows exist.
      clarification — once per round, when NEEDS_CLARIFICATION + message row ready.
      complete      — when status == GENERATED.
      error         — when status == FAILED, or persona disappears.

    Sets stop_event on any terminal state.
    Always puts _DONE on the queue in its finally block.
    """
    sent_files: set[str] = set()
    skills_sent = False
    clarification_sent: set[int] = set()

    engine = create_async_engine(str(settings.DATABASE_URL), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            while not stop_event.is_set():
                # Force a real DB round-trip — never trust the identity-map
                # cache in a long-running poll loop.
                result = await db.execute(
                    select(Persona)
                    .where(Persona.id == persona_id)
                    .execution_options(populate_existing=True)
                )
                persona = result.scalar_one_or_none()

                if persona is None:
                    await queue.put(
                        _sse(
                            "error",
                            {
                                "code": "NOT_FOUND",
                                "message": "Persona no longer exists.",
                            },
                        )
                    )
                    stop_event.set()
                    break

                # ── Emit new file columns ──────────────────────────────────
                for col in FILE_COLUMNS:
                    if col not in sent_files:
                        content = getattr(persona, col)
                        if content:
                            await queue.put(_sse("file", {"file": col, "content": content}))
                            sent_files.add(col)

                # ── Emit skills once they appear ───────────────────────────
                if not skills_sent:
                    skills = await _get_skills(persona_id, db)
                    if skills:
                        await queue.put(_sse("skills", {"skills": skills}))
                        skills_sent = True

                # ── Clarification ──────────────────────────────────────────
                if persona.status == PersonaStatus.NEEDS_CLARIFICATION:
                    round_num = persona.clarification_rounds
                    if round_num not in clarification_sent:
                        questions = await _fetch_clarification_message(persona_id, round_num, db)
                        if questions is not None:
                            # questions == [] is still a valid (empty) list —
                            # emit it so the client knows a round started.
                            await queue.put(
                                _sse(
                                    "clarification",
                                    {
                                        "round": round_num,
                                        "questions": questions,
                                    },
                                )
                            )
                            clarification_sent.add(round_num)
                        # If questions is None the message row wasn't ready yet;
                        # fall through and poll again after POLL_INTERVAL.
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # ── Terminal: success ──────────────────────────────────────
                if persona.status == PersonaStatus.GENERATED:
                    # One final sweep for any files that arrived this cycle.
                    for col in FILE_COLUMNS:
                        if col not in sent_files:
                            content = getattr(persona, col)
                            if content:
                                await queue.put(_sse("file", {"file": col, "content": content}))
                                sent_files.add(col)

                    if not skills_sent:
                        skills = await _get_skills(persona_id, db)
                        if skills:
                            await queue.put(_sse("skills", {"skills": skills}))

                    await queue.put(
                        _sse(
                            "complete",
                            {
                                "persona_id": str(persona_id),
                                "name": persona.name,
                                "category": persona.category,
                                "description": persona.description_summary,
                            },
                        )
                    )
                    stop_event.set()
                    break

                # ── Terminal: failure ──────────────────────────────────────
                if persona.status == PersonaStatus.FAILED:
                    await queue.put(
                        _sse(
                            "error",
                            {
                                "code": persona.error_code or "GENERATION_FAILED",
                                "message": "Persona generation failed.",
                            },
                        )
                    )
                    stop_event.set()
                    break

                await asyncio.sleep(POLL_INTERVAL)

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("stream: DB poller error for persona %s", persona_id)
        stop_event.set()
    finally:
        await queue.put(_DONE)
        await engine.dispose()


async def _listen_redis_for_errors(
    persona_id: uuid.UUID,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
) -> None:
    """
    Lightweight Redis listener — only forwards 'error' events.

    This gives faster failure notification when the Celery task publishes a
    terminal error (e.g. CLARIFICATION_TIMEOUT, INTERNAL_ERROR) before the
    DB poller's next POLL_INTERVAL tick catches it via status == FAILED.

    Clarification events are intentionally NOT handled here; _poll_db is
    the single source of truth for them to avoid race conditions between
    the Redis publish and the ConversationMessage commit.
    """
    channel = f"persona:{persona_id}:events"
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()

    try:
        await pubsub.subscribe(channel)

        while not stop_event.is_set():
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5),
                    timeout=1.0,
                )
            except TimeoutError:
                continue

            if not message or message.get("type") != "message":
                continue

            try:
                payload = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("stream: malformed Redis message for persona %s", persona_id)
                continue

            if payload.get("type") == "error":
                await queue.put(
                    _sse(
                        "error",
                        {
                            "code": payload.get("code", "GENERATION_FAILED"),
                            "message": payload.get("message", "Persona generation failed."),
                        },
                    )
                )
                stop_event.set()
                break

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("stream: Redis error-listener error for persona %s", persona_id)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        await redis_client.aclose()


async def stream_generation(
    persona_id: uuid.UUID,
    persona: Persona,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """
    Main entry point called by the stream endpoint.

    Always emits a 'start' event immediately so clients know the connection
    is live before any generation work begins.

    Handles already-terminal states in a fast path (no background tasks).
    For in-progress personas, runs _poll_db (primary) and
    _listen_redis_for_errors (fast error notification) concurrently.

    The `db` parameter is the request-scoped session used only for the
    fast-path reads. _poll_db opens its own NullPool session.
    """
    # Always emit start so the client knows the stream is healthy.
    yield _sse("start", {"persona_id": str(persona_id)})

    # ── Fast-path: already terminal ────────────────────────────────────────
    if persona.status == PersonaStatus.GENERATED:
        for col in FILE_COLUMNS:
            content = getattr(persona, col)
            if content:
                yield _sse("file", {"file": col, "content": content})

        skills = await _get_skills(persona_id, db)
        if skills:
            yield _sse("skills", {"skills": skills})

        yield _sse(
            "complete",
            {
                "persona_id": str(persona_id),
                "name": persona.name,
                "category": persona.category,
                "description": persona.description_summary,
            },
        )
        return

    if persona.status == PersonaStatus.FAILED:
        yield _sse(
            "error",
            {
                "code": persona.error_code or "GENERATION_FAILED",
                "message": "Persona generation failed.",
            },
        )
        return

    # ── Live path: spin up background tasks ───────────────────────────────
    queue: asyncio.Queue[str | object] = asyncio.Queue()
    stop_event = asyncio.Event()

    db_task = asyncio.create_task(
        _poll_db(persona_id, queue, stop_event),
        name=f"db-poller-{persona_id}",
    )
    redis_task = asyncio.create_task(
        _listen_redis_for_errors(persona_id, queue, stop_event),
        name=f"redis-error-listener-{persona_id}",
    )

    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item  # type: ignore[misc]

    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        redis_task.cancel()
        db_task.cancel()
        await asyncio.gather(redis_task, db_task, return_exceptions=True)
