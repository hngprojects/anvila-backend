import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """
    Subscribes to persona:{persona_id}:events and forwards
    clarification events into the queue.

    Runs until stop_event is set (set by the DB poller when it
    detects a terminal state or by the generator on client disconnect).

    If the prompt was clear and Celery never publishes to this channel,
    this task just sits quietly until stop_event fires — it never blocks
    the DB poller.
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

            if payload.get("type") == "clarification":
                await queue.put(
                    _sse(
                        "clarification",
                        {
                            "round": payload.get("round", 0),
                            "questions": payload.get("questions", []),
                        },
                    )
                )

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
    db: AsyncSession,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
) -> None:
    """
    Polls the persona row every POLL_INTERVAL seconds.
    Emits file events as columns become non-null.
    Emits skills event once PersonaSkill records exist.
    Emits complete or error on terminal status, then sets stop_event.

    This task drives the stream lifecycle. It is the one that
    sets stop_event to signal the Redis listener to shut down.
    """
    sent_files: set[str] = set()
    skills_sent = False

    try:
        while not stop_event.is_set():
            await asyncio.sleep(POLL_INTERVAL)
            await db.refresh(persona := await db.get(Persona, persona_id))

            # Emit any newly populated file columns
            for col in FILE_COLUMNS:
                if col not in sent_files:
                    content = getattr(persona, col)
                    if content:
                        await queue.put(_sse("file", {"file": col, "content": content}))
                        sent_files.add(col)

            # Emit skills once they appear
            if not skills_sent:
                skills = await _get_skills(persona_id, db)
                if skills:
                    await queue.put(_sse("skills", {"skills": skills}))
                    skills_sent = True

            # Check terminal states
            if persona.status == PersonaStatus.GENERATED:
                # Flush any remaining files before complete
                for col in FILE_COLUMNS:
                    if col not in sent_files:
                        content = getattr(persona, col)
                        if content:
                            await queue.put(_sse("file", {"file": col, "content": content}))

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

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("stream: DB poller error for persona %s", persona_id)
        stop_event.set()
    finally:
        await queue.put(_DONE)


async def stream_generation(
    persona_id: uuid.UUID,
    persona: Persona,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """
    Main entry point called by the endpoint.
    Handles already-terminal states immediately, otherwise
    starts the concurrent Redis listener + DB poller.

    Yields SSE-formatted strings.
    """

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
        _poll_db(persona_id, db, queue, stop_event),
        name=f"db-poller-{persona_id}",
    )

    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break

            yield item

    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        redis_task.cancel()
        db_task.cancel()

        await asyncio.gather(redis_task, db_task, return_exceptions=True)
