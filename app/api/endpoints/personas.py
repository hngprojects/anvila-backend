import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import CurrentUser, DBSession
from app.core.config import settings
from app.core.paginator import PageParams, PaginatedMeta, paginate
from app.core.security import decode_token
from app.models.chat_session import ChatSession
from app.models.enums import PersonaStatus
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.services.auth import get_user_by_id

router = APIRouter(prefix="/personas", tags=["personas"])
POLL_INTERVAL = 1.5


class SkillOut(BaseModel):
    slug: str
    name: str
    description: str
    tags: list[str]


class PersonaSummary(BaseModel):
    id: uuid.UUID
    name: str
    description_summary: str
    category: str
    status: str
    visibility: str
    github_repo_url: str | None
    created_at: datetime
    published_at: datetime | None


class PersonaListResponse(BaseModel):
    personas: list[PersonaSummary]
    meta: PaginatedMeta


class PersonaDetail(BaseModel):
    id: uuid.UUID
    name: str
    description_summary: str
    category: str
    status: str
    visibility: str
    github_repo_url: str | None
    github_clone_url: str | None
    github_zip_url: str | None
    published_at: datetime | None
    created_at: datetime
    identity_md: str | None
    soul_md: str | None
    dna_md: str | None
    overview_md: str | None
    heartbeat_md: str | None
    readme_md: str | None
    skills: list[SkillOut]


async def _get_skills(persona_id: uuid.UUID, db: AsyncSession) -> list[SkillOut]:
    result = await db.execute(
        select(Skill)
        .join(PersonaSkill, PersonaSkill.skill_id == Skill.id)
        .where(PersonaSkill.persona_id == persona_id)
    )
    return [
        SkillOut(slug=s.slug, name=s.name, description=s.description, tags=s.tags or [])
        for s in result.scalars().all()
    ]


@router.get("", response_model=PersonaListResponse)
async def list_personas(
    user: CurrentUser,
    db: DBSession,
    params: Annotated[PageParams, Depends()],
    status: str | None = Query(None, description="Filter by persona status"),
):
    """
    All non-deleted personas for the current user.
    Supports ?status= filter and standard ?page= / ?size= pagination.
    """
    filters = [
        Persona.user_id == user.id,
        Persona.deleted_at == None,  # noqa
    ]
    if status:
        filters.append(Persona.status == status)

    query = select(Persona).where(and_(*filters)).order_by(Persona.created_at.desc())
    rows, meta = await paginate(db, query, params)

    return PersonaListResponse(
        personas=[
            PersonaSummary(
                id=p.id,
                name=p.name,
                description_summary=p.description_summary,
                category=p.category,
                status=p.status,
                visibility=p.visibility,
                github_repo_url=p.github_repo_url,
                created_at=p.created_at,
                published_at=p.published_at,
            )
            for p in rows.all()
        ],
        meta=meta,
    )


@router.get("/{persona_id}", response_model=PersonaDetail)
async def get_persona(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
):
    """
    Full persona detail with file contents and attached skills.
    Owner only — 404 for non-owners.
    """
    persona = await db.get(Persona, persona_id)
    if not persona or persona.user_id != user.id or persona.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Persona not found")

    skills = await _get_skills(persona_id, db)

    return PersonaDetail(
        id=persona.id,
        name=persona.name,
        description_summary=persona.description_summary,
        category=persona.category,
        status=persona.status,
        visibility=persona.visibility,
        github_repo_url=persona.github_repo_url,
        github_clone_url=persona.github_clone_url,
        github_zip_url=persona.github_zip_url,
        published_at=persona.published_at,
        created_at=persona.created_at,
        identity_md=persona.identity_md,
        soul_md=persona.soul_md,
        dna_md=persona.dna_md,
        overview_md=persona.overview_md,
        heartbeat_md=persona.heartbeat_md,
        readme_md=persona.readme_md,
        skills=skills,
    )


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
):
    """
    Soft delete a persona and all its chat sessions.
    Does not delete the GitHub repo.
    Celery Beat hard-deletes after 30 days.
    """
    persona = await db.get(Persona, persona_id)
    if not persona or persona.user_id != user.id or persona.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Persona not found")

    now = datetime.now(UTC)

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.persona_id == persona_id,
            ChatSession.deleted_at == None,  # noqa
        )
    )
    for session in result.scalars().all():
        session.deleted_at = now

    persona.deleted_at = now
    await db.commit()


FILE_COLUMNS = [
    "identity_md",
    "soul_md",
    "dna_md",
    "overview_md",
    "heartbeat_md",
    "readme_md",
]


class PersonaStatusResponse(BaseModel):
    persona_id: uuid.UUID
    status: str
    files_completed: list[str]
    files_total: int
    skills_matched: bool
    name: str | None
    category: str | None
    description: str | None
    error_code: str | None


@router.get("/{persona_id}/status", response_model=PersonaStatusResponse)
async def get_persona_status(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
):
    """
    Returns current generation status for a persona.
    files_completed: list of file column names that are non-null.
    skills_matched: true when at least one PersonaSkill record exists.
    error_code: populated only when status is FAILED — treat as terminal.
    """
    persona = await db.get(Persona, persona_id)

    if not persona or persona.user_id != user.id:
        raise HTTPException(status_code=404, detail="Persona not found")

    files_completed = [col for col in FILE_COLUMNS if getattr(persona, col) is not None]

    result = await db.execute(
        select(PersonaSkill).where(PersonaSkill.persona_id == persona_id).limit(1)
    )
    skills_matched = result.scalar_one_or_none() is not None

    return PersonaStatusResponse(
        persona_id=persona_id,
        status=persona.status,
        files_completed=files_completed,
        files_total=len(FILE_COLUMNS),
        skills_matched=skills_matched,
        name=persona.name,
        category=persona.category,
        description=persona.description_summary,
        error_code=persona.error_code,
    )


def _sse(event: str, data: dict) -> str:
    """Format a server-sent event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _get_persona_skills(persona_id: uuid.UUID, db: AsyncSession) -> list[dict]:
    """Fetch full skill objects attached to a persona."""
    result = await db.execute(
        select(Skill)
        .join(PersonaSkill, PersonaSkill.skill_id == Skill.id)
        .where(PersonaSkill.persona_id == persona_id)
    )
    skills = result.scalars().all()
    return [
        {
            "slug": s.slug,
            "name": s.name,
            "description": s.description,
            "tags": s.tags or [],
        }
        for s in skills
    ]


@router.get("/{persona_id}/stream")
async def stream_persona(
    persona_id: uuid.UUID,
    db: DBSession,
    # JWT passed as query param because EventSource does not support headers
    token: str = Query(..., description="JWT access token"),
):
    """
    SSE stream for persona generation progress.

    Events emitted:
      clarification — LLM needs more info. Payload: {round, questions}
      file          — A file was saved. Payload: {file: "identity_md", content: "..."}
      skills        — Skills resolved. Payload: {skills: [...]}
      complete      — Generation done. Payload: {persona_id, name, category, description}
      error         — Terminal failure. Payload: {code, message}

    The stream stays open through multiple clarification rounds.
    It closes automatically on complete or error.
    """
    payload = decode_token(token, expected_purpose="access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    persona = await db.get(Persona, persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    if persona.user_id != user_id:
        raise HTTPException(status_code=404, detail="Persona not found")

    async def event_generator():
        sent_files: set[str] = set()
        skills_sent = False

        # Handle already-terminal states on connect.
        # This covers the case where the user refreshes mid-generation
        # or reconnects after navigating away.
        if persona.status == PersonaStatus.GENERATED:
            for col in FILE_COLUMNS:
                content = getattr(persona, col)
                if content:
                    yield _sse("file", {"file": col, "content": content})

            # Send skills
            skills = await _get_persona_skills(persona_id, db)
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

        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        channel = f"persona:{persona_id}:events"
        await pubsub.subscribe(channel)

        try:
            while True:
                # ── Check Redis for clarification events ──────────────────
                # Non-blocking get — check if Celery published anything
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message and message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        if payload.get("type") == "clarification":
                            yield _sse(
                                "clarification",
                                {
                                    "round": payload["round"],
                                    "questions": payload["questions"],
                                },
                            )
                    except (json.JSONDecodeError, KeyError):
                        pass

                await db.refresh(persona)

                for col in FILE_COLUMNS:
                    if col not in sent_files:
                        content = getattr(persona, col)
                        if content:
                            yield _sse("file", {"file": col, "content": content})
                            sent_files.add(col)

                # Send skills once they appear
                if not skills_sent:
                    skills = await _get_persona_skills(persona_id, db)
                    if skills:
                        yield _sse("skills", {"skills": skills})
                        skills_sent = True

                # Check for terminal states
                if persona.status == PersonaStatus.GENERATED:
                    yield _sse(
                        "complete",
                        {
                            "persona_id": str(persona_id),
                            "name": persona.name,
                            "category": persona.category,
                            "description": persona.description_summary,
                        },
                    )
                    break

                if persona.status == PersonaStatus.FAILED:
                    yield _sse(
                        "error",
                        {
                            "code": persona.error_code or "GENERATION_FAILED",
                            "message": "Persona generation failed.",
                        },
                    )
                    break

                # Wait before next poll
                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await redis_client.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disables nginx buffering
            "Connection": "keep-alive",
        },
    )
