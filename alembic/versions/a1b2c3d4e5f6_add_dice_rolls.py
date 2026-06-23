"""add dice_rolls table + sessions.dice_enabled (dice / skill checks §4c)

Revision ID: a1b2c3d4e5f6
Revises: e7d1c9b2a3f4
Create Date: 2026-06-22 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e7d1c9b2a3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Crockford-base32 ULID guard, matching app.models._id_check / ULID_REGEX.
_ULID_REGEX = "^[0-7][0-9A-HJKMNP-TV-Z]{25}$"


def upgrade() -> None:
    op.add_column('sessions', sa.Column('dice_enabled', sa.Boolean(), nullable=True))
    op.create_table(
        'dice_rolls',
        sa.Column('id', sa.String(length=26), nullable=False),
        sa.Column('session_id', sa.String(length=26), nullable=False),
        sa.Column('turn_id', sa.String(length=26), nullable=True),
        sa.Column('skill_label', sa.String(length=60), nullable=False),
        sa.Column('dc', sa.Integer(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('die', sa.Integer(), nullable=False),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['turn_id'], ['turns.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(f"id ~ '{_ULID_REGEX}'", name='ck_dice_rolls_id_ulid'),
    )
    op.create_index(op.f('ix_dice_rolls_session_id'), 'dice_rolls', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_dice_rolls_session_id'), table_name='dice_rolls')
    op.drop_table('dice_rolls')
    op.drop_column('sessions', 'dice_enabled')
