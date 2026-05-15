from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship, mapped_column, Mapped
from api.v1.models.base_model import BaseTableModel


class ResetPasswordToken(BaseTableModel):
    """Represents password reset tokens"""

    __tablename__ = "reset_password_tokens"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_reset_password_tokens_token_hash", "token_hash"),
        Index("ix_reset_password_tokens_user_id", "user_id"),
    )

    user = relationship("User", back_populates="reset_password_token")
