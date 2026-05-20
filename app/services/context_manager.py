from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession


def _format_answers(answers: list[dict]) -> str:
    return "\n".join(f"Q: {a['id']}\nA: {a['answer']}" for a in answers)


class ContextManager:
    async def compress(
        self,
        session: ChatSession,
        new_answers: list[dict],
        db: AsyncSession,
    ) -> str:
        block = _format_answers(new_answers)
        if session.compressed_context:
            updated = f"{session.compressed_context}\n\n{block}"
        else:
            updated = f"User intent:\n{block}"

        session.compressed_context = updated
        await db.commit()
        return updated

    def build_followup_prompt(
        self,
        session: ChatSession,
        answers: list[dict],
        system_prompt: str,
    ) -> str:
        separator = "---"
        context = session.compressed_context or ""
        answers_block = _format_answers(answers) if answers else ""
        return (
            f"{system_prompt}\n"
            f"{separator}\n"
            f"CONTEXT SO FAR:\n{context}\n"
            f"{separator}\n"
            f"LATEST ANSWERS:\n{answers_block}\n"
            f"Continue generation or ask further questions."
        )
