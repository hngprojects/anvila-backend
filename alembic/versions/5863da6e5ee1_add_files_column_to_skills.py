"""add files column to skills

Revision ID: 5863da6e5ee1
Revises: add009d81e1b
Create Date: 2026-05-30 15:48:24.572320

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5863da6e5ee1"
down_revision: Union[str, None] = "add009d81e1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column(
            "files",
            postgresql.JSONB,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("skills", "files")
