"""initial roleplay schema

Revision ID: bde43a419b6b
Revises:
Create Date: 2026-04-16 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = 'bde43a419b6b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSION = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "character_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("hard_rules", sa.Text(), nullable=False),
        sa.Column("style_guide", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "world_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("canon", sa.Text(), nullable=False),
        sa.Column("hard_rules", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("character_card_id", sa.String(length=36), nullable=False),
        sa.Column("world_state_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_summarized_turn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["character_card_id"], ["character_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["world_state_id"], ["world_states.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_character_card_id", "sessions", ["character_card_id"], unique=False)
    op.create_index("ix_sessions_world_state_id", "sessions", ["world_state_id"], unique=False)
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"], unique=False)

    op.create_table(
        "turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("continuity_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "turn_index", name="uq_turn_session_index"),
    )
    op.create_index("ix_turns_session_id", "turns", ["session_id"], unique=False)
    op.create_index("ix_turns_created_at", "turns", ["created_at"], unique=False)

    op.create_table(
        "memory_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("character_card_id", sa.String(length=36), nullable=True),
        sa.Column("source_turn_id", sa.String(length=36), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["character_card_id"], ["character_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_turn_id"], ["turns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_facts_session_id", "memory_facts", ["session_id"], unique=False)
    op.create_index("ix_memory_facts_created_at", "memory_facts", ["created_at"], unique=False)
    op.create_index("ix_memory_facts_importance", "memory_facts", ["importance"], unique=False)
    op.create_index(
        "ix_memory_facts_embedding_hnsw",
        "memory_facts",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "episode_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("start_turn_index", sa.Integer(), nullable=False),
        sa.Column("end_turn_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_episode_summaries_session_id", "episode_summaries", ["session_id"], unique=False)
    op.create_index("ix_episode_summaries_created_at", "episode_summaries", ["created_at"], unique=False)
    op.create_index("ix_episode_summaries_importance", "episode_summaries", ["importance"], unique=False)
    op.create_index(
        "ix_episode_summaries_embedding_hnsw",
        "episode_summaries",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "relationship_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("source_entity", sa.String(length=120), nullable=False),
        sa.Column("target_entity", sa.String(length=120), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("last_observed_turn_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["last_observed_turn_id"], ["turns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_relationship_states_session_id", "relationship_states", ["session_id"], unique=False)
    op.create_index("ix_relationship_states_importance", "relationship_states", ["importance"], unique=False)
    op.create_index("ix_relationship_states_updated_at", "relationship_states", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_relationship_states_updated_at", table_name="relationship_states")
    op.drop_index("ix_relationship_states_importance", table_name="relationship_states")
    op.drop_index("ix_relationship_states_session_id", table_name="relationship_states")
    op.drop_table("relationship_states")

    op.drop_index("ix_episode_summaries_embedding_hnsw", table_name="episode_summaries")
    op.drop_index("ix_episode_summaries_importance", table_name="episode_summaries")
    op.drop_index("ix_episode_summaries_created_at", table_name="episode_summaries")
    op.drop_index("ix_episode_summaries_session_id", table_name="episode_summaries")
    op.drop_table("episode_summaries")

    op.drop_index("ix_memory_facts_embedding_hnsw", table_name="memory_facts")
    op.drop_index("ix_memory_facts_importance", table_name="memory_facts")
    op.drop_index("ix_memory_facts_created_at", table_name="memory_facts")
    op.drop_index("ix_memory_facts_session_id", table_name="memory_facts")
    op.drop_table("memory_facts")

    op.drop_index("ix_turns_created_at", table_name="turns")
    op.drop_index("ix_turns_session_id", table_name="turns")
    op.drop_table("turns")

    op.drop_index("ix_sessions_created_at", table_name="sessions")
    op.drop_index("ix_sessions_world_state_id", table_name="sessions")
    op.drop_index("ix_sessions_character_card_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_table("world_states")
    op.drop_table("character_cards")
