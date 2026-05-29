import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy import and_, case, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import CanGenerate, CurrentUser, DBSession
from app.core.config import settings
from app.core.paginator import PageParams, paginate
from app.core.security import decode_token
from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import (
    MessageRole,
    PersonaCategory,
    PersonaStatus,
    PersonaVisibility,
)
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.models.user import User
from app.schemas.personas import (
    ClarifyRequest,
    ClarifyResponse,
    GenerateResponse,
    PersonaDetail,
    PersonaStatusResponse,
    PersonaSummary,
    PublishPersonaResponse,
    SkillOut,
)
from app.schemas.shared import ApiResponse
from app.services.auth import get_user_by_id
from app.services.context_manager import ContextManager
from app.services.file_extractor import extract_text
from app.services.prompt_sanitizer import PromptSanitizer
from app.services.publish_service import publish_persona
from app.services.stream_service import stream_generation
from app.worker.tasks.generation import generate_persona

MAX_CLARIFICATION_ROUNDS = 5
POLL_INTERVAL = 1.5
router = APIRouter(prefix="/personas", tags=["personas"])


@router.post(
    "/generate",
    response_model=ApiResponse[GenerateResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate(
    user: CanGenerate,
    db: DBSession,
    prompt: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
) -> ApiResponse[GenerateResponse]:
    sanitizer = PromptSanitizer()
    try:
        sanitized_prompt = sanitizer.sanitize(prompt)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "EMPTY_PROMPT", "message": "Prompt is empty after sanitization."},
        ) from exc

    file_content: str | None = None
    if file is not None and file.filename:
        try:
            file_content = await extract_text(file)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "UNSUPPORTED_FILE_TYPE", "message": str(exc)},
            ) from exc

    persona = Persona(
        user_id=user.id,
        name="Untitled",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        category=PersonaCategory.DEVELOPMENT,
        description_summary="",
        visibility=PersonaVisibility.PUBLIC,
        status=PersonaStatus.DRAFT,
    )
    db.add(persona)
    await db.flush()

    session = ChatSession(
        persona_id=persona.id,
        user_id=user.id,
        last_message_at=datetime.now(UTC),
    )
    db.add(session)
    await db.flush()

    db.add(
        ConversationMessage(
            session_id=session.id,
            persona_id=persona.id,
            role=MessageRole.USER,
            content=sanitized_prompt,
            round_number=0,
        )
    )

    user.generation_count += 1
    await db.commit()

    try:
        task = generate_persona.delay(  # type: ignore
            str(persona.id),
            str(session.id),
            sanitized_prompt,
            file_content,
        )
    except Exception as exc:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                generation_count=case(
                    (User.generation_count > 0, User.generation_count - 1),
                    else_=0,
                )
            )
        )
        persona.status = PersonaStatus.FAILED
        persona.error_code = "QUEUE_UNAVAILABLE"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "QUEUE_UNAVAILABLE", "message": "Failed to queue generation job."},
        ) from exc
    persona.job_id = task.id
    await db.commit()

    return ApiResponse[GenerateResponse](
        message="Generation queued.",
        data=GenerateResponse(
            status="queued",
            persona_id=persona.id,
            session_id=session.id,
            job_id=task.id,
        ),
    )


@router.post(
    "/{persona_id}/clarify",
    response_model=ApiResponse[ClarifyResponse],
)
async def clarify(
    persona_id: uuid.UUID,
    body: ClarifyRequest,
    user: CurrentUser,
    db: DBSession,
) -> ApiResponse[ClarifyResponse]:
    persona = await db.get(Persona, persona_id)
    if persona is None or persona.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")

    session = await db.get(ChatSession, body.session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.persona_id != persona_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session does not belong to this persona",
        )

    if session.clarification_round >= MAX_CLARIFICATION_ROUNDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MAX_ROUNDS_REACHED",
                "message": "Maximum clarification rounds reached.",
            },
        )

    sanitizer = PromptSanitizer()
    sanitized_answers: list[dict] = []
    for answer in body.answers:
        try:
            cleaned = sanitizer.sanitize(answer.answer)
        except ValueError:
            continue
        sanitized_answers.append({"id": answer.id, "answer": cleaned})

    if not sanitized_answers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "EMPTY_ANSWERS",
                "message": "All answers were empty after sanitization.",
            },
        )

    current_round = session.clarification_round + 1
    await ContextManager().compress(
        persona_id=persona_id, round_number=current_round, answers=sanitized_answers, db=db
    )

    session.clarification_round += 1
    await db.commit()

    redis_client = Redis.from_url(settings.REDIS_URL)
    try:
        await redis_client.publish(
            f"persona:{persona_id}:continue",
            json.dumps({"type": "continue", "session_id": str(session.id)}),
        )
    finally:
        await redis_client.aclose()

    return ApiResponse[ClarifyResponse](
        message="Clarification recorded.",
        data=ClarifyResponse(status="clarifying", round=session.clarification_round),
    )


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


@router.get("", response_model=ApiResponse[list[PersonaSummary]])
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
    if status and status in PersonaStatus:
        filters.append(Persona.status == status)

    query = select(Persona).where(and_(*filters)).order_by(Persona.created_at.desc())
    rows, meta = await paginate(db, query, params)
    return ApiResponse[list[PersonaSummary]](
        message="Personas retrieved.",
        data=[PersonaSummary.model_validate(r, from_attributes=True) for r in rows],
        meta=meta.model_dump(),
    )


@router.get("/{persona_id}", response_model=ApiResponse[PersonaDetail])
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

    data = PersonaDetail(
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
    return ApiResponse[PersonaDetail](message="Persona retrieved.", data=data)


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


@router.get("/{persona_id}/status", response_model=ApiResponse[PersonaStatusResponse])
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

    if not persona or persona.user_id != user.id or persona.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Persona not found")

    files_completed = [col for col in FILE_COLUMNS if getattr(persona, col) is not None]

    result = await db.execute(
        select(PersonaSkill).where(PersonaSkill.persona_id == persona_id).limit(1)
    )
    skills_matched = result.scalar_one_or_none() is not None

    data = PersonaStatusResponse(
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
    return ApiResponse[PersonaStatusResponse](message="Status retrieved.", data=data)


@router.get("/{persona_id}/stream")
async def stream_persona(
    persona_id: uuid.UUID,
    db: DBSession,
    token: Annotated[str, Query(description="JWT access token")],
):
    """
    SSE stream for persona generation progress.
    JWT is passed as a query param because EventSource does not support headers.

    Events:
      clarification — {round, questions}
      file          — {file: "identity_md", content: "..."}
      skills        — {skills: [...]}
      complete      — {persona_id, name, category, description}
      error         — {code, message}
    """
    # Validate token
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
    if not persona or persona.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")

    return StreamingResponse(
        stream_generation(persona_id, persona, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/{persona_id}/publish",
    summary="Publish persona markdown files to GitHub",
    status_code=status.HTTP_200_OK,
    response_model=ApiResponse[PublishPersonaResponse],
)
async def publish_persona_to_github(
    persona_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    persona: Persona | None = await db.get(Persona, persona_id)

    if not persona or persona.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Persona not found")

    if persona.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your persona")

    persona = await publish_persona(persona, db)
    await db.refresh(persona)

    data = PublishPersonaResponse(
        persona_id=persona.id,
        status=persona.status,
        published_at=persona.published_at,
        github_repo_url=persona.github_repo_url,
        github_clone_url=persona.github_clone_url,
        github_zip_url=persona.github_zip_url,
    )

    return ApiResponse[PublishPersonaResponse](message="Persona published to GitHub.", data=data)
