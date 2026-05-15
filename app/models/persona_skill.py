import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.persona import Persona
    from app.models.skill import Skill


class PersonaSkill(BaseModel):
    __tablename__ = "persona_skills"

    __table_args__ = (UniqueConstraint("persona_id", "skill_id", name="uq_persona_skill"),)

    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id"),
        nullable=False,
    )

    # relationships
    persona: Mapped["Persona"] = relationship(back_populates="persona_skills")
    skill: Mapped["Skill"] = relationship(back_populates="persona_skills")
