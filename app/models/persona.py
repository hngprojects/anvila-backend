import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import PersonaCategory, PersonaStatus, PersonaVisibility

if TYPE_CHECKING:
    from app.models.persona_skill import PersonaSkill
    from app.models.user import User


class Persona(BaseModel):
    __tablename__ = "personas"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    category: Mapped[PersonaCategory] = mapped_column(String(50), nullable=False)
    description_summary: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[PersonaVisibility] = mapped_column(String(10), nullable=False)
    status: Mapped[PersonaStatus] = mapped_column(
        String(30),
        nullable=False,
        default=PersonaStatus.DRAFT,
        server_default=PersonaStatus.DRAFT,
    )
    clarification_rounds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    github_repo_url: Mapped[str | None] = mapped_column(Text)
    github_clone_url: Mapped[str | None] = mapped_column(Text)
    github_zip_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # relationships
    user: Mapped["User"] = relationship(back_populates="personas")
    persona_skills: Mapped[list["PersonaSkill"]] = relationship(
        back_populates="persona",
        cascade="all, delete-orphan",
    )
