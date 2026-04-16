"""head compatibility revision

Revision ID: 8d30b9929c21
Revises: a6fda81ba534
Create Date: 2026-04-16 00:00:02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d30b9929c21'
down_revision: Union[str, None] = 'a6fda81ba534'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
