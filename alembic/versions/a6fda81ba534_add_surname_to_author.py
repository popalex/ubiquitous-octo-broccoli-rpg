"""no-op compatibility revision

Revision ID: a6fda81ba534
Revises: bde43a419b6b
Create Date: 2026-04-16 00:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6fda81ba534'
down_revision: Union[str, None] = 'bde43a419b6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
