"""add sessions.parent_session_id + forked_at_turn (rewind & fork)

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-06-14 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('parent_session_id', sa.String(length=36), nullable=True))
    op.add_column('sessions', sa.Column('forked_at_turn', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_sessions_parent_session_id'), 'sessions', ['parent_session_id'], unique=False
    )
    op.create_foreign_key(
        'fk_sessions_parent_session_id',
        'sessions',
        'sessions',
        ['parent_session_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_sessions_parent_session_id', 'sessions', type_='foreignkey')
    op.drop_index(op.f('ix_sessions_parent_session_id'), table_name='sessions')
    op.drop_column('sessions', 'forked_at_turn')
    op.drop_column('sessions', 'parent_session_id')
