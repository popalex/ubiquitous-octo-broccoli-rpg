"""add per-session feature overrides

Revision ID: a7b8c9d0e1f2
Revises: f3a4b5c6d7e8
Create Date: 2026-06-12 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL = inherit the global setting, so existing sessions keep behavior.
    op.add_column('sessions', sa.Column('world_state_enabled', sa.Boolean(), nullable=True))
    op.add_column('sessions', sa.Column('quests_enabled', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('sessions', 'quests_enabled')
    op.drop_column('sessions', 'world_state_enabled')
