import json
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy import case, update

from app.api.deps import CanGenerate, CurrentUser, DBSession
from app.core.config import settings
from app.models.chat_session import ChatSession
from app.models.conversation_message import ConversationMessage
from app.models.enums import (
    MessageRole,
    PersonaCategory,
    PersonaStatus,
    PersonaVisibility,
)
from app.models.persona import Persona
from app.models.user import User
from app.schemas.personas import (
    ClarifyRequest,
    ClarifyResponse,
    GenerateResponse,
)
from app.schemas.shared import ApiResponse
from app.services.context_manager import ContextManager
from app.services.file_extractor import extract_text
from app.services.prompt_sanitizer import PromptSanitizer
from app.worker.tasks.generation import generate_persona

MAX_CLARIFICATION_ROUNDS = 5

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

    session = ChatSession(persona_id=persona.id, user_id=user.id)
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
        task = generate_persona.delay(
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

    for entry in sanitized_answers:
        db.add(
            ConversationMessage(
                session_id=session.id,
                persona_id=persona.id,
                role=MessageRole.USER,
                content=entry["answer"],
                round_number=session.clarification_round,
            )
        )
    await db.flush()

    await ContextManager().compress(session, sanitized_answers, db)

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
