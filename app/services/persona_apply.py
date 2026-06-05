from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_message import ConversationMessage
from app.models.enums import MessageRole, PersonaCategory
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.services.readme_builder import build_readme

logger = logging.getLogger(__name__)

PERSONA_FILE_COLUMNS = ("identity_md", "soul_md", "dna_md", "overview_md", "heartbeat_md")


async def apply_generation(
    parsed: dict,
    persona: Persona,
    db: AsyncSession,
    after_files_applied: Callable[[], Awaitable[None]] | None = None,
) -> list[Skill]:
    """Apply a validated generation payload to a persona.

    The caller owns terminal status and commit behavior. This helper mutates
    persona fields, replaces PersonaSkill links, and rebuilds readme_md.
    """
    files = parsed["files"]
    category = parsed["category"]
    if category not in {c.value for c in PersonaCategory}:
        raise ValueError(f"invalid category: {category!r}")
    if not isinstance(files, dict):
        raise TypeError("files must be an object")

    persona.name = parsed["persona_name"]
    persona.category = category
    persona.description_summary = parsed["short_description"]
    for col in PERSONA_FILE_COLUMNS:
        setattr(persona, col, files[col])

    await db.flush()
    if after_files_applied is not None:
        await after_files_applied()

    from app.services.skill_matcher import match_skills

    try:
        skills = await match_skills(
            parsed.get("suggested_skills", []),
            category,
            db,
        )
    except NotImplementedError:
        logger.warning(
            "match_skills stub pending; proceeding with empty skills for persona %s",
            persona.id,
        )
        skills = []
    except Exception:
        logger.exception(
            "match_skills raised unexpectedly for persona %s; continuing without skills",
            persona.id,
        )
        skills = []

    await db.execute(delete(PersonaSkill).where(PersonaSkill.persona_id == persona.id))
    for skill in skills:
        db.add(PersonaSkill(persona_id=persona.id, skill_id=skill.id))

    try:
        persona.readme_md = build_readme(
            {
                "name": persona.name,
                "category": persona.category,
                "description_summary": persona.description_summary,
            },
            skills,
        )
    except Exception:
        logger.exception("build_readme failed for persona %s; using empty readme", persona.id)
        persona.readme_md = ""

    return skills


async def build_refine_transcript(
    persona_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession,
    exclude_message_id: uuid.UUID | None = None,
) -> str:
    """Build the prior refine transcript from persisted conversation rows."""
    query = select(ConversationMessage).where(
        ConversationMessage.persona_id == persona_id,
        ConversationMessage.session_id == session_id,
    )
    if exclude_message_id is not None:
        query = query.where(ConversationMessage.id != exclude_message_id)

    result = await db.execute(
        query.order_by(ConversationMessage.created_at, ConversationMessage.id)
    )

    lines: list[str] = []
    for message in result.scalars().all():
        label = "User" if message.role == MessageRole.USER else "Assistant"
        lines.append(f"{label}: {message.content}")
    return "\n".join(lines)
