"""add HP/resources + stakes + permadeath (todo-rpg Phase 3)

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-06-24 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Backfill HP for any sheets that predate this migration (matches the default
# sheet_hp_start; new sheets are seeded from settings at creation).
_DEFAULT_HP = "20"


def upgrade() -> None:
    # HP on the character sheet (server_default backfills existing rows).
    op.add_column('character_sheets', sa.Column('hp', sa.Integer(), nullable=False, server_default=_DEFAULT_HP))
    op.add_column('character_sheets', sa.Column('max_hp', sa.Integer(), nullable=False, server_default=_DEFAULT_HP))
    # Failure severity tag on a resolved check (none/minor/major).
    op.add_column('dice_rolls', sa.Column('stakes', sa.String(length=20), nullable=True))
    # Per-session permadeath override (NULL inherits the global setting).
    op.add_column('sessions', sa.Column('permadeath_enabled', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('sessions', 'permadeath_enabled')
    op.drop_column('dice_rolls', 'stakes')
    op.drop_column('character_sheets', 'max_hp')
    op.drop_column('character_sheets', 'hp')
