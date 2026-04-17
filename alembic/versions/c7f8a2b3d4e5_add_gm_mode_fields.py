"""add GM mode fields to sessions and turns

Revision ID: c7f8a2b3d4e5
Revises: 8d30b9929c21
Create Date: 2026-04-17 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7f8a2b3d4e5'
down_revision: Union[str, None] = '8d30b9929c21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add GM mode fields to sessions table
    op.add_column('sessions', sa.Column('gm_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('sessions', sa.Column('current_location', sa.String(length=200), nullable=True))
    op.add_column('sessions', sa.Column('time_of_day', sa.String(length=50), nullable=True))
    op.add_column('sessions', sa.Column('last_event_turn', sa.Integer(), nullable=False, server_default=sa.text('0')))

    # Add turn_type field to turns table
    op.add_column('turns', sa.Column('turn_type', sa.String(length=32), nullable=False, server_default=sa.text("'chat'")))


def downgrade() -> None:
    # Remove turn_type from turns
    op.drop_column('turns', 'turn_type')

    # Remove GM mode fields from sessions
    op.drop_column('sessions', 'last_event_turn')
    op.drop_column('sessions', 'time_of_day')
    op.drop_column('sessions', 'current_location')
    op.drop_column('sessions', 'gm_enabled')
