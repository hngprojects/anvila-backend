"""add github oauth tables

Revision ID: e1f2a3b4c5d6
Revises: b2c3d4e5f6a7
Create Date: 2026-05-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("github_subject", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_users_github_subject"),
        "users",
        ["github_subject"],
        unique=True,
    )

    op.create_table(
        "oauth_link_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_oauth_link_tokens_token_hash"),
        "oauth_link_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_oauth_link_tokens_user_id"),
        "oauth_link_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_link_tokens_user_provider",
        "oauth_link_tokens",
        ["user_id", "provider"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_link_tokens_expires_at",
        "oauth_link_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oauth_link_tokens_expires_at",
        table_name="oauth_link_tokens",
    )
    op.drop_index(
        "ix_oauth_link_tokens_user_provider",
        table_name="oauth_link_tokens",
    )
    op.drop_index(
        op.f("ix_oauth_link_tokens_user_id"),
        table_name="oauth_link_tokens",
    )
    op.drop_index(
        op.f("ix_oauth_link_tokens_token_hash"),
        table_name="oauth_link_tokens",
    )
    op.drop_table("oauth_link_tokens")
    op.drop_index(op.f("ix_users_github_subject"), table_name="users")
    op.drop_column("users", "github_subject")
