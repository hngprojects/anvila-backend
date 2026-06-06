import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.clarification_store import (
    FormattedQuestion,
    build_context_block,
    load_all_rounds,
    upsert_answers,
)

logger = logging.getLogger(__name__)


class ContextManager:
    async def compress(
        self,
        persona_id: uuid.UUID,
        round_number: int,
        answers: list[dict],
        db: AsyncSession,
    ) -> str:
        """
        Upsert answers into the stored question row for `round_number`,
        then rebuild compressed_context on the ChatSession from all rounds.

        Returns the updated compressed_context string.
        """
        from sqlalchemy import select

        from app.models.chat_session import ChatSession

        updated_questions = await upsert_answers(
            persona_id=persona_id,
            round_number=round_number,
            answers=answers,
            db=db,
        )

        if updated_questions is None:
            logger.warning(
                "context_manager: upsert_answers returned None for persona %s round %d; "
                "compressed_context not updated",
                persona_id,
                round_number,
            )

        all_rounds = await load_all_rounds(persona_id, db)
        compressed = _build_compressed_context(all_rounds)

        result = await db.execute(select(ChatSession).where(ChatSession.persona_id == persona_id))
        session = result.scalar_one_or_none()
        if session is not None:
            session.compressed_context = compressed
            await db.flush()
        else:
            logger.warning(
                "context_manager: no ChatSession found for persona %s; "
                "could not persist compressed_context",
                persona_id,
            )

        return compressed

    def build_followup_prompt(
        self,
        compressed_context: str,
        system_prompt: str,
    ) -> str:
        """
        Build a follow-up prompt for the LLM using the already-compressed
        context string.

        The context contains full question text and answers, so the LLM
        has everything it needs with no memory of previous calls.
        """
        separator = "---"
        return (
            f"{system_prompt}\n"
            f"{separator}\n"
            f"CONTEXT SO FAR:\n{compressed_context}\n"
            f"{separator}\n"
            f"Continue generation or ask further questions."
        )

    def build_refine_prompt(
        self,
        compressed_context: str,
        persona_files: dict[str, str],
        user_message: str,
        system_prompt: str,
    ) -> str:
        """
        Build a prompt for a refinement request.

        Includes the full existing persona files so the LLM has complete
        context of what was generated, plus the conversation history and
        the new user message.
        """
        separator = "---"
        files_block = "\n\n".join(
            f"<{col}>\n{content}\n</{col}>" for col, content in persona_files.items() if content
        )
        context_block = (
            f"CONTEXT SO FAR:\n{compressed_context}\n{separator}\n" if compressed_context else ""
        )

        return (
            f"{system_prompt}\n"
            f"{separator}\n"
            f"EXISTING PERSONA FILES:\n{files_block}\n"
            f"{separator}\n"
            f"{context_block}"
            f"USER MESSAGE:\n{user_message}\n"
            f"{separator}\n"
            f"Respond with plain text or generation JSON according to the system prompt."
        )


def _build_compressed_context(all_rounds: list[list[FormattedQuestion]]) -> str:
    """
    Build a full compressed context string from all clarification rounds.
    """
    blocks: list[str] = []
    for i, questions in enumerate(all_rounds, start=1):
        block = build_context_block(questions)
        if block:
            blocks.append(f"Round {i}:\n{block}")

    return "\n\n".join(blocks)
