"""add world_state_ledger table

Revision ID: d9e1f2a3b4c5
Revises: c7f8a2b3d4e5
Create Date: 2026-06-09 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e1f2a3b4c5'
down_revision: Union[str, None] = 'c7f8a2b3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'world_state_ledger',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('turn_id', sa.String(length=36), nullable=True),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['turn_id'], ['turns.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'version', name='uq_world_state_ledger_session_version'),
    )
    op.create_index(op.f('ix_world_state_ledger_session_id'), 'world_state_ledger', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_world_state_ledger_session_id'), table_name='world_state_ledger')
    op.drop_table('world_state_ledger')
