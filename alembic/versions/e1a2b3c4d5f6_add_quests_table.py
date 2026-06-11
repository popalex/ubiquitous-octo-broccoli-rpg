"""add quests table

Revision ID: e1a2b3c4d5f6
Revises: d9e1f2a3b4c5
Create Date: 2026-06-10 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, None] = 'd9e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'quests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('quest_type', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('stakes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('origin', sa.String(length=32), nullable=False),
        sa.Column('stages', sa.JSON(), nullable=False),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.Column('created_turn', sa.Integer(), nullable=False),
        sa.Column('accepted_turn', sa.Integer(), nullable=True),
        sa.Column('last_progress_turn', sa.Integer(), nullable=False),
        sa.Column('last_escalation_turn', sa.Integer(), nullable=False),
        sa.Column('resolved_turn', sa.Integer(), nullable=True),
        sa.Column('source_turn_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_turn_id'], ['turns.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'slug', name='uq_quest_session_slug'),
    )
    op.create_index(op.f('ix_quests_session_id'), 'quests', ['session_id'], unique=False)
    op.create_index(op.f('ix_quests_status'), 'quests', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_quests_status'), table_name='quests')
    op.drop_index(op.f('ix_quests_session_id'), table_name='quests')
    op.drop_table('quests')
