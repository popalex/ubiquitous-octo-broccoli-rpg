from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base


EMBEDDING_DIMENSION = get_settings().embedding_dimension


def new_id() -> str:
    return str(uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CharacterCard(TimestampMixin, Base):
    __tablename__ = "character_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hard_rules: Mapped[str] = mapped_column(Text, nullable=False)
    style_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sessions: Mapped[list["Session"]] = relationship(back_populates="character_card")


class WorldState(TimestampMixin, Base):
    __tablename__ = "world_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    canon: Mapped[str] = mapped_column(Text, nullable=False)
    hard_rules: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sessions: Mapped[list["Session"]] = relationship(back_populates="world_state")


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    character_card_id: Mapped[str] = mapped_column(ForeignKey("character_cards.id", ondelete="CASCADE"), index=True)
    world_state_id: Mapped[str | None] = mapped_column(ForeignKey("world_states.id", ondelete="SET NULL"), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_summarized_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # GM mode fields
    gm_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    current_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    time_of_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_event_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    character_card: Mapped[CharacterCard] = relationship(back_populates="sessions")
    world_state: Mapped[WorldState | None] = relationship(back_populates="sessions")
    turns: Mapped[list["Turn"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    memory_facts: Mapped[list["MemoryFact"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    episode_summaries: Mapped[list["EpisodeSummary"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    relationship_states: Mapped[list["RelationshipState"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    world_state_ledgers: Mapped[list["WorldStateLedger"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Turn(TimestampMixin, Base):
    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("session_id", "turn_index", name="uq_turn_session_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    continuity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # GM mode field: 'chat', 'gm_narration', 'gm_event'
    turn_type: Mapped[str] = mapped_column(String(32), default="chat", nullable=False)

    session: Mapped[Session] = relationship(back_populates="turns")


class MemoryFact(TimestampMixin, Base):
    __tablename__ = "memory_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    character_card_id: Mapped[str | None] = mapped_column(ForeignKey("character_cards.id", ondelete="SET NULL"), nullable=True)
    source_turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, index=True, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped[Session] = relationship(back_populates="memory_facts")


class EpisodeSummary(TimestampMixin, Base):
    __tablename__ = "episode_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    start_turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    end_turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, index=True, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped[Session] = relationship(back_populates="episode_summaries")


class WorldStateLedger(Base):
    """Versioned, structured canon for a session — the authoritative record of
    what is *true* (entities, inventory, threads, location, facts).

    Distinct from :class:`WorldState`, which is the static world *template*
    (setting/canon text shared across sessions). Each turn that changes canon
    writes a new immutable version row; the latest version is current canon.
    """

    __tablename__ = "world_state_ledger"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_world_state_ledger_session_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The turn that produced this version (nullable: backfill/manual edits).
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[Session] = relationship(back_populates="world_state_ledgers")


class RelationshipState(TimestampMixin, Base):
    __tablename__ = "relationship_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False)
    target_entity: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5, index=True, nullable=False)
    last_observed_turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)

    session: Mapped[Session] = relationship(back_populates="relationship_states")
