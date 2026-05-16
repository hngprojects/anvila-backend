from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import UserPlan, UserProvider

if TYPE_CHECKING:
    from app.models.persona import Persona
    from app.models.refresh_token import RefreshToken


class User(BaseModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[UserProvider] = mapped_column(
        String(20),
        nullable=False,
    )
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    plan: Mapped[UserPlan] = mapped_column(
        String(20),
        nullable=False,
        default=UserPlan.FREE,
        server_default=UserPlan.FREE,
    )
    github_username: Mapped[str | None] = mapped_column(String(100))
    google_subject: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        index=True,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # relationships
    personas: Mapped[list["Persona"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
