"""add turns.retcon_note

Revision ID: f3a4b5c6d7e8
Revises: e1a2b3c4d5f6
Create Date: 2026-06-12 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('turns', sa.Column('retcon_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('turns', 'retcon_note')
