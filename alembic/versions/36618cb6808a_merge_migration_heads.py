"""merge migration heads

Revision ID: 36618cb6808a
Revises: 2d37d86295d1, e65a69fe5c00
Create Date: 2026-05-22 21:59:03.752350

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36618cb6808a'
down_revision: Union[str, None] = ('2d37d86295d1', 'e65a69fe5c00')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
