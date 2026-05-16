"""update password reset tokens

Revision ID: 20260515154445
Revises:
Create Date: 2026-05-15

Replaces the stateless JWT approach (jti column) with a DB-backed
token_hash approach. Drops jti, adds token_hash / expires_at / used_at,
keeps the unique constraint on user_id (one active token per user),
and adds a unique index on token_hash.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260515154445"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return inspect(conn).has_table(table_name)


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    cols = [c["name"] for c in inspect(conn).get_columns(table_name)]
    return column_name in cols


def _index_exists(conn, table_name: str, index_name: str) -> bool:
    idxs = [i["name"] for i in inspect(conn).get_indexes(table_name)]
    return index_name in idxs


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "reset_password_tokens"):
        # Fresh install — create the table with the correct schema.
        op.create_table(
            "reset_password_tokens",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("user_id", name="uq_reset_password_tokens_user_id"),
        )
        op.create_index(
            "ix_reset_password_tokens_token_hash",
            "reset_password_tokens",
            ["token_hash"],
            unique=True,
        )
        return

    # Existing table — migrate from old JWT schema to DB-backed schema.

    # 1. Add new columns (nullable first so existing rows don't violate NOT NULL).
    if not _column_exists(conn, "reset_password_tokens", "token_hash"):
        op.add_column(
            "reset_password_tokens",
            sa.Column("token_hash", sa.String(64), nullable=True),
        )
    if not _column_exists(conn, "reset_password_tokens", "expires_at"):
        op.add_column(
            "reset_password_tokens",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists(conn, "reset_password_tokens", "used_at"):
        op.add_column(
            "reset_password_tokens",
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 2. Wipe stale rows (they used the old jti/JWT scheme and are now invalid).
    op.execute("DELETE FROM reset_password_tokens")

    # 3. Enforce NOT NULL on the new required columns now that rows are cleared.
    op.alter_column("reset_password_tokens", "token_hash", nullable=False)
    op.alter_column("reset_password_tokens", "expires_at", nullable=False)

    # 4. Drop the old jti column.
    if _column_exists(conn, "reset_password_tokens", "jti"):
        op.drop_column("reset_password_tokens", "jti")

    # 5. Ensure unique constraint on user_id exists (one active token per user).
    constraints = inspect(conn).get_unique_constraints("reset_password_tokens")
    has_user_id_unique = any("user_id" in uc["column_names"] for uc in constraints)
    if not has_user_id_unique:
        op.create_unique_constraint(
            "uq_reset_password_tokens_user_id",
            "reset_password_tokens",
            ["user_id"],
        )

    # 6. Create unique index on token_hash.
    if not _index_exists(conn, "reset_password_tokens", "ix_reset_password_tokens_token_hash"):
        op.create_index(
            "ix_reset_password_tokens_token_hash",
            "reset_password_tokens",
            ["token_hash"],
            unique=True,
        )


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_index("ix_reset_password_tokens_token_hash", "reset_password_tokens")
    op.drop_constraint(
        "uq_reset_password_tokens_user_id", "reset_password_tokens", type_="unique"
    )

    if not _column_exists(conn, "reset_password_tokens", "jti"):
        op.add_column(
            "reset_password_tokens",
            sa.Column("jti", sa.String(), nullable=True),
        )

    for col in ("token_hash", "expires_at", "used_at"):
        if _column_exists(conn, "reset_password_tokens", col):
            op.drop_column("reset_password_tokens", col)
