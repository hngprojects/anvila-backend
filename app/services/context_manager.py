from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession


class ContextManager:
    async def compress(
        self,
        session: ChatSession,
        new_answers: list[dict],  # [{"id": str, "answer": str}]
        db: AsyncSession,
    ) -> str:
        # Produce a compact intent summary from the existing context
        # and the latest answers.
        #
        # Logic:
        #   - Read session.compressed_context (may be None on first round)
        #   - Format new_answers as Q&A pairs:
        #       "Q: {question_id}\nA: {answer}"
        #   - If previous context exists:
        #       append the new Q&A block to it
        #   - If no previous context:
        #       start fresh with the new Q&A block
        #   - Save the new summary to session.compressed_context in DB
        #   - Commit the DB session
        #
        # Returns the new compressed_context string.
        # This string is what gets sent to the LLM on the next call —
        # not the full message history.
        raise NotImplementedError

    def build_followup_prompt(
        self,
        session: ChatSession,
        answers: list[dict],  # [{"id": str, "answer": str}]
        system_prompt: str,
    ) -> str:
        # Build the complete prompt string for a follow-up LLM call.
        #
        # Structure (in order):
        #   1. system_prompt  (the unified generation system prompt)
        #   2. A separator line
        #   3. "CONTEXT SO FAR:\n" + session.compressed_context
        #   4. A separator line
        #   5. "LATEST ANSWERS:\n" + formatted answers
        #   6. "Continue generation or ask further questions."
        #
        # Does NOT include full message history.
        # Does NOT call the LLM — pure string construction.
        #
        # Returns the complete prompt string ready to pass to
        # LLMAdapter.generate() as the `prompt` argument.
        raise NotImplementedError
