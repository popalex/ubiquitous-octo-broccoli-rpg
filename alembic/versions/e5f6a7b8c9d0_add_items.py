"""add items table + sessions.items_enabled (todo-rpg Phase 4)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-25 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Crockford-base32 ULID guard, matching app.models._id_check / ULID_REGEX.
_ULID_REGEX = "^[0-7][0-9A-HJKMNP-TV-Z]{25}$"


def upgrade() -> None:
    op.add_column('sessions', sa.Column('items_enabled', sa.Boolean(), nullable=True))
    op.create_table(
        'items',
        sa.Column('id', sa.String(length=26), nullable=False),
        sa.Column('session_id', sa.String(length=26), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('equipped', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('consumable', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('effect_type', sa.String(length=20), nullable=True),
        sa.Column('effect_value', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('effect_attribute', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(f"id ~ '{_ULID_REGEX}'", name='ck_items_id_ulid'),
    )
    op.create_index(op.f('ix_items_session_id'), 'items', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_items_session_id'), table_name='items')
    op.drop_table('items')
    op.drop_column('sessions', 'items_enabled')
