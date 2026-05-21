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
from app.models.enums import PersonaStatus
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.5

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


async def _listen_redis(
    persona_id: uuid.UUID,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
) -> None:
    """Subscribe to persona:{id}:events and forward events to the queue.

    Handles:
      clarification — forwarded as-is to the stream client.
      error         — forwarded to the stream client, then stop_event is set
                      so _poll_db exits on its next iteration (fast-path
                      shutdown on Celery task failure).

    Runs until stop_event is set (driven by _poll_db on terminal DB state,
    or by this task itself on a Redis error event).
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

            if not message:
                continue

            if message.get("type") != "message":
                continue

            try:
                payload = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("stream: malformed Redis message for persona %s", persona_id)
                continue

            msg_type = payload.get("type")

            if msg_type == "clarification":
                await queue.put(
                    _sse(
                        "clarification",
                        {
                            "round": payload.get("round", 0),
                            "questions": payload.get("questions", []),
                        },
                    )
                )

            elif msg_type == "error":
                # Celery task published a terminal error — surface it
                # immediately and stop waiting.
                await queue.put(
                    _sse(
                        "error",
                        {
                            "code": payload.get("code", "GENERATION_FAILED"),
                            "message": payload.get("message", "Persona generation failed."),
                        },
                    )
                )
                # Signal _poll_db to stop on its next iteration.
                stop_event.set()
                break

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("stream: Redis listener error for persona %s", persona_id)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        await redis_client.aclose()


async def _poll_db(
    persona_id: uuid.UUID,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
) -> None:
    """Poll the persona row on its own dedicated DB session.

    Uses NullPool so it never competes with the request-scoped session for
    a connection — avoids asyncpg "another operation is in progress" errors.

    Emits:
      file      — once per column, as soon as the column becomes non-null.
      skills    — once, as soon as PersonaSkill rows exist.
      complete  — when status == GENERATED (after flushing any remaining files).
      error     — when status == FAILED (belt-and-suspenders; Celery task also
                  publishes to Redis for faster delivery).

    Sets stop_event on any terminal state, which causes _listen_redis to exit.
    Always puts _DONE on the queue in its finally block so stream_generation
    stops yielding.
    """
    sent_files: set[str] = set()
    skills_sent = False

    engine = create_async_engine(str(settings.DATABASE_URL), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            while not stop_event.is_set():
                # Force a real DB round-trip on every cycle — never trust the
                # identity-map cache for a long-running poll loop.
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

                # Emit any newly populated file columns.
                for col in FILE_COLUMNS:
                    if col not in sent_files:
                        content = getattr(persona, col)
                        if content:
                            await queue.put(_sse("file", {"file": col, "content": content}))
                            sent_files.add(col)

                # Emit skills once they appear.
                if not skills_sent:
                    skills = await _get_skills(persona_id, db)
                    if skills:
                        await queue.put(_sse("skills", {"skills": skills}))
                        skills_sent = True

                # ── Terminal: success ──────────────────────────────────────
                if persona.status == PersonaStatus.GENERATED:
                    # Flush any files that arrived in this same poll cycle
                    # but weren't caught above.
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
                    # Only emit here if stop_event isn't already set — if
                    # _listen_redis already forwarded the Redis error event
                    # and set stop_event, we skip the duplicate.
                    if not stop_event.is_set():
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


async def stream_generation(
    persona_id: uuid.UUID,
    persona: Persona,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Main entry point called by the stream endpoint.

    Handles already-terminal states immediately (no background tasks needed).
    For in-progress personas, starts _listen_redis and _poll_db concurrently.

    The `db` parameter is the request-scoped session and is only used here
    for the already-terminal fast-path reads. _poll_db opens its own session
    with NullPool to avoid concurrent-use errors.
    """
    # ── Fast-path: already done ────────────────────────────────────────────
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

    queue: asyncio.Queue[str | object] = asyncio.Queue()
    stop_event = asyncio.Event()

    redis_task = asyncio.create_task(
        _listen_redis(persona_id, queue, stop_event),
        name=f"redis-listener-{persona_id}",
    )
    db_task = asyncio.create_task(
        _poll_db(persona_id, queue, stop_event),
        name=f"db-poller-{persona_id}",
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
