import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FormattedQuestion:
    """Internal representation of one clarification question."""

    __slots__ = ("id", "question", "options", "answer")

    def __init__(
        self,
        id: str,
        question: str,
        options: list[str],
        answer: str | None = None,
    ) -> None:
        self.id = id
        self.question = question
        self.options = options
        self.answer = answer

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "options": self.options,
            "answer": self.answer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FormattedQuestion":
        return cls(
            id=data["id"],
            question=data["question"],
            options=data.get("options", []),
            answer=data.get("answer"),
        )


def format_questions(raw_questions: list[dict]) -> list[FormattedQuestion]:
    """
    Convert raw LLM question dicts into FormattedQuestion objects.

    Raw shape (from LLM):
        {"id": "...", "question": "...", "options": [...], "allow_custom": true}

    Stored shape:
        {"id": "...", "question": "...", "options": [...], "answer": null}
    """
    formatted: list[FormattedQuestion] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            logger.warning("clarification_store: skipping non-dict question item: %r", item)
            continue
        q_id = item.get("id")
        question = item.get("question")
        if not q_id or not question:
            logger.warning(
                "clarification_store: skipping question missing id or question text: %r", item
            )
            continue
        formatted.append(
            FormattedQuestion(
                id=str(q_id),
                question=str(question),
                options=list(item.get("options") or []),
                answer=None,
            )
        )
    return formatted


def serialize_questions(questions: list[FormattedQuestion]) -> str:
    """Serialize a list of FormattedQuestion to a JSON string for DB storage."""
    return json.dumps({"questions": [q.to_dict() for q in questions]})


async def store_questions(
    persona_id: uuid.UUID,
    session_id: uuid.UUID,
    round_number: int,
    raw_questions: list[dict],
    db: AsyncSession,
) -> list[FormattedQuestion]:
    """
    Format raw LLM questions and persist them as an assistant
    ConversationMessage for the given round.

    Returns the list of FormattedQuestion that was stored.
    """
    from app.models.conversation_message import ConversationMessage
    from app.models.enums import MessageRole

    formatted = format_questions(raw_questions)
    db.add(
        ConversationMessage(
            session_id=session_id,
            persona_id=persona_id,
            role=MessageRole.ASSISTANT,
            content=serialize_questions(formatted),
            round_number=round_number,
        )
    )
    await db.flush()
    return formatted


async def upsert_answers(
    persona_id: uuid.UUID,
    round_number: int,
    answers: list[dict],
    db: AsyncSession,
) -> list[FormattedQuestion] | None:
    """
    Find the assistant ConversationMessage for `round_number` and fill in
    the answers in-place on the matching questions.

    Returns the updated list of FormattedQuestion, or None if the message
    row was not found.
    """
    from app.models.conversation_message import ConversationMessage
    from app.models.enums import MessageRole

    result = await db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.persona_id == persona_id,
            ConversationMessage.role == MessageRole.ASSISTANT,
            ConversationMessage.round_number == round_number,
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    msg = result.scalar_one_or_none()

    if msg is None:
        logger.warning(
            "clarification_store: no assistant message found for persona %s round %d",
            persona_id,
            round_number,
        )
        return None

    try:
        stored = json.loads(msg.content)
        questions = [FormattedQuestion.from_dict(q) for q in stored["questions"]]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning(
            "clarification_store: could not parse stored questions for persona %s round %d: %s",
            persona_id,
            round_number,
            exc,
        )
        return None

    # Build a lookup from id → answer string
    answer_map: dict[str, str] = {}
    for entry in answers:
        a_id = entry.get("id")
        a_val = entry.get("answer")
        if a_id and a_val is not None:
            answer_map[str(a_id)] = str(a_val)

    matched_ids: set[str] = set()
    for q in questions:
        if q.id in answer_map:
            q.answer = answer_map[q.id]
            matched_ids.add(q.id)

    unmatched = set(answer_map.keys()) - matched_ids
    if unmatched:
        logger.warning(
            "clarification_store: answer ids not matched to any question "
            "for persona %s round %d: %s",
            persona_id,
            round_number,
            unmatched,
        )

    msg.content = serialize_questions(questions)
    await db.flush()
    return questions


def build_context_block(questions: list[FormattedQuestion]) -> str:
    """
    Produce an explicit Q&A block for LLM context using full question text.

    Only includes questions that have been answered. Returns an empty string
    if no answers exist yet.

    Example output:
        Q: What is the persona's primary role?
        A: Sales representative focused on enterprise clients
    """
    lines: list[str] = []
    for q in questions:
        if q.answer is not None:
            lines.append(f"Q: {q.question}")
            lines.append(f"A: {q.answer}")
    return "\n".join(lines)


async def load_all_rounds(
    persona_id: uuid.UUID,
    db: AsyncSession,
) -> list[list[FormattedQuestion]]:
    """
    Load all clarification rounds for a persona, ordered by round_number.

    Returns a list of question lists — one per round. Useful for rebuilding
    full context when constructing a refinement prompt.
    """
    from app.models.conversation_message import ConversationMessage
    from app.models.enums import MessageRole

    result = await db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.persona_id == persona_id,
            ConversationMessage.role == MessageRole.ASSISTANT,
        )
        .order_by(ConversationMessage.round_number.asc(), ConversationMessage.created_at.asc())
        .execution_options(populate_existing=True)
    )
    messages = result.scalars().all()

    rounds: list[list[FormattedQuestion]] = []
    for msg in messages:
        try:
            stored = json.loads(msg.content)
            if "questions" not in stored:
                continue
            questions = [FormattedQuestion.from_dict(q) for q in stored["questions"]]
            rounds.append(questions)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "clarification_store: skipping unparseable message for persona %s", persona_id
            )
            continue

    return rounds
