"""add upgraded_at to users

Revision ID: add009d81e1b
Revises: 36618cb6808a
Create Date: 2026-05-22 16:45:20.409610

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add009d81e1b'
down_revision: Union[str, None] = '36618cb6808a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("upgraded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "upgraded_at")
