from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import PersonaCategory, SkillSourceRegistry

if TYPE_CHECKING:
    from app.models.persona_skill import PersonaSkill


class Skill(BaseModel):
    __tablename__ = "skills"
    __table_args__ = (Index("ix_skills_tags", "tags", postgresql_using="gin"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    files: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    category: Mapped[PersonaCategory | None] = mapped_column(String(50), index=True)
    tags: Mapped[list | None] = mapped_column(ARRAY(String))
    source_registry: Mapped[SkillSourceRegistry] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    source_author: Mapped[str | None] = mapped_column(String(200))
    install_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # relationships
    persona_skills: Mapped[list["PersonaSkill"]] = relationship(back_populates="skill")
