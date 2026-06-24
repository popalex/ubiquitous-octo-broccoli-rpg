"""add character_sheets + sheet competence on dice_rolls (todo-rpg Phases 1+2)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-24 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Crockford-base32 ULID guard, matching app.models._id_check / ULID_REGEX.
_ULID_REGEX = "^[0-7][0-9A-HJKMNP-TV-Z]{25}$"


def upgrade() -> None:
    # Per-session override (NULL = inherit the global setting, so existing
    # sessions keep behavior).
    op.add_column('sessions', sa.Column('character_sheet_enabled', sa.Boolean(), nullable=True))

    # Level-up beats produced by a turn, persisted so a reload re-renders them.
    op.add_column('turns', sa.Column('advancement_json', sa.JSON(), nullable=True))

    # Character-sheet competence on existing skill checks. modifier defaults to 0;
    # total backfills to the raw die (no sheet was in play when these rolled).
    op.add_column('dice_rolls', sa.Column('attribute', sa.String(length=20), nullable=True))
    op.add_column(
        'dice_rolls',
        sa.Column('modifier', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('dice_rolls', sa.Column('total', sa.Integer(), nullable=True))
    op.execute('UPDATE dice_rolls SET total = die WHERE total IS NULL')
    op.alter_column('dice_rolls', 'total', nullable=False)

    op.create_table(
        'character_sheets',
        sa.Column('id', sa.String(length=26), nullable=False),
        sa.Column('session_id', sa.String(length=26), nullable=False),
        sa.Column('might', sa.Integer(), nullable=False),
        sa.Column('finesse', sa.Integer(), nullable=False),
        sa.Column('wits', sa.Integer(), nullable=False),
        sa.Column('presence', sa.Integer(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('xp', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', name='uq_character_sheet_session'),
        sa.CheckConstraint(f"id ~ '{_ULID_REGEX}'", name='ck_character_sheets_id_ulid'),
    )
    op.create_index(op.f('ix_character_sheets_session_id'), 'character_sheets', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_character_sheets_session_id'), table_name='character_sheets')
    op.drop_table('character_sheets')
    op.drop_column('dice_rolls', 'total')
    op.drop_column('dice_rolls', 'modifier')
    op.drop_column('dice_rolls', 'attribute')
    op.drop_column('turns', 'advancement_json')
    op.drop_column('sessions', 'character_sheet_enabled')
