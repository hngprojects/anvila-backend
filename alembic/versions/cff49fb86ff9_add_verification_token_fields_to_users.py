"""add verification token fields to users

Revision ID: cff49fb86ff9
Revises: 9e38c7d41d38
Create Date: 2026-05-15 22:12:24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cff49fb86ff9"
down_revision: Union[str, None] = "9e38c7d41d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("verification_token_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("verification_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_users_verification_token_hash"),
        "users",
        ["verification_token_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_verification_token_hash"), table_name="users")
    op.drop_column("users", "verification_token_expires_at")
    op.drop_column("users", "verification_token_hash")
