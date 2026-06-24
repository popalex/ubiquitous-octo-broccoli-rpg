from __future__ import annotations

import re
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.config import get_settings
from app.db import Base

EMBEDDING_DIMENSION = get_settings().embedding_dimension

# Entity IDs are canonical 26-char ULIDs (Crockford base32, time-sortable).
# ULID storage width; the column type below. A ULID is shorter than a UUID, so
# this also structurally rejects legacy 36-char UUIDs.
ULID_LENGTH = 26
# Crockford base32 alphabet excludes I, L, O, U.
ULID_REGEX = "^[0-7][0-9A-HJKMNP-TV-Z]{25}$"
_ULID_RE = re.compile(ULID_REGEX)

# The id column type, shared by every primary key. Foreign-key columns inherit
# this type from the referenced column via SQLAlchemy's ForeignKey inference, so
# the whole ID graph is String(26) without restating it on every FK.
IdType = String(ULID_LENGTH)


def new_id() -> str:
    """Generate a fresh entity ID as a canonical 26-char ULID."""
    return str(ULID())


def is_ulid(value: str) -> bool:
    """True if ``value`` is a canonical 26-char Crockford-base32 ULID."""
    return bool(_ULID_RE.match(value))


def _id_check(table: str) -> CheckConstraint:
    """DB-level guard that a table's primary key is a well-formed ULID.

    Kept in the model (not only the migration) so the schema built by
    ``create_all`` in tests matches the migrated production schema.
    """
    return CheckConstraint(f"id ~ '{ULID_REGEX}'", name=f"ck_{table}_id_ulid")


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
    __table_args__ = (_id_check("character_cards"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hard_rules: Mapped[str] = mapped_column(Text, nullable=False)
    style_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sessions: Mapped[list[Session]] = relationship(back_populates="character_card")


class WorldState(TimestampMixin, Base):
    __tablename__ = "world_states"
    __table_args__ = (_id_check("world_states"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    canon: Mapped[str] = mapped_column(Text, nullable=False)
    hard_rules: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sessions: Mapped[list[Session]] = relationship(back_populates="world_state")


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (_id_check("sessions"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    character_card_id: Mapped[str] = mapped_column(ForeignKey("character_cards.id", ondelete="CASCADE"), index=True)
    world_state_id: Mapped[str | None] = mapped_column(ForeignKey("world_states.id", ondelete="SET NULL"), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_summarized_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # GM mode fields
    gm_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    suggestions_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    current_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    time_of_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_event_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Per-session feature overrides; NULL inherits the global Settings flag
    # (resolution in app/services/features.py).
    world_state_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    quests_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    dice_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    character_sheet_enabled: Mapped[bool | None] = mapped_column(nullable=True)

    # Rewind & fork (§4a): set on a session created by forking another at a
    # given turn. NULL parent = an original chronicle. The parent is never
    # mutated (fork-only, no destructive rewind). FK is SET NULL so deleting a
    # parent orphans its forks rather than cascade-deleting them.
    parent_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    forked_at_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    character_card: Mapped[CharacterCard] = relationship(back_populates="sessions")
    world_state: Mapped[WorldState | None] = relationship(back_populates="sessions")
    turns: Mapped[list[Turn]] = relationship(back_populates="session", cascade="all, delete-orphan")
    memory_facts: Mapped[list[MemoryFact]] = relationship(back_populates="session", cascade="all, delete-orphan")
    episode_summaries: Mapped[list[EpisodeSummary]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    relationship_states: Mapped[list[RelationshipState]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    world_state_ledgers: Mapped[list[WorldStateLedger]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    quests: Mapped[list[Quest]] = relationship(back_populates="session", cascade="all, delete-orphan")
    dice_rolls: Mapped[list[DiceRoll]] = relationship(back_populates="session", cascade="all, delete-orphan")
    character_sheet: Mapped[CharacterSheet | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )


class Turn(TimestampMixin, Base):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", name="uq_turn_session_index"),
        _id_check("turns"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    continuity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Continuity violations found *after* a streamed reply was already shown;
    # injected into the next context packet as a hard constraint (retcon).
    retcon_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # GM mode field: 'chat', 'gm_narration', 'gm_event'
    turn_type: Mapped[str] = mapped_column(String(32), default="chat", nullable=False)

    session: Mapped[Session] = relationship(back_populates="turns")


class MemoryFact(TimestampMixin, Base):
    __tablename__ = "memory_facts"
    __table_args__ = (_id_check("memory_facts"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    character_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("character_cards.id", ondelete="SET NULL"), nullable=True
    )
    source_turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, index=True, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped[Session] = relationship(back_populates="memory_facts")


class EpisodeSummary(TimestampMixin, Base):
    __tablename__ = "episode_summaries"
    __table_args__ = (_id_check("episode_summaries"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
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
        _id_check("world_state_ledger"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The turn that produced this version (nullable: backfill/manual edits).
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped[Session] = relationship(back_populates="world_state_ledgers")


class Quest(TimestampMixin, Base):
    """An AI-tracked narrative arc for a session — a mystery, a promise the
    player made, a social arc, a moral dilemma, or an escalating threat.

    Quests are offered by GM plot-hook events (``origin="gm_event"``) or
    detected from player commitments in roleplay (``origin="emergent"``).
    A post-turn LLM judge advances stages and resolves them; quests neglected
    for too long escalate via GM consequence events. Distinct from ledger
    threads (one-line canon notes) — quests carry stages, stakes, and turn
    bookkeeping. Gated behind ``QUESTS_ENABLED``.
    """

    __tablename__ = "quests"
    __table_args__ = (
        UniqueConstraint("session_id", "slug", name="uq_quest_session_slug"),
        _id_check("quests"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # mystery | promise | social | dilemma | threat
    quest_type: Mapped[str] = mapped_column(String(32), default="promise", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    stakes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # rumored | offered | active | escalating | completed | failed | abandoned
    status: Mapped[str] = mapped_column(String(32), default="offered", nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(32), default="emergent", nullable=False)  # gm_event | emergent
    stages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{id, description, done}]
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_progress_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_escalation_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)

    session: Mapped[Session] = relationship(back_populates="quests")


class DiceRoll(TimestampMixin, Base):
    """A server-rolled d20 skill check resolved in GM mode (§4c).

    When the player attempts an uncertain action, the GM assesses a descriptive
    ``skill_label`` and a difficulty ``dc`` (competence lives in the DC — there
    is no character stat block — and ``rationale`` records *why* that DC, so the
    UI/logs can show it). The server rolls ``die`` (1-20); ``outcome`` is one of
    ``success`` / ``failure`` / ``critical_success`` (nat 20). There is no
    critical-failure tier by design. Persisted for auditability and to re-render
    the roll in a chronicle's transcript. Gated behind ``DICE_ENABLED``.
    """

    __tablename__ = "dice_rolls"
    __table_args__ = (_id_check("dice_rolls"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    # The assistant turn this roll resolved (SET NULL keeps the audit row if the
    # turn is ever removed). Nullable because the roll is computed mid-stream,
    # before the turn row exists.
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"), nullable=True)
    skill_label: Mapped[str] = mapped_column(String(60), nullable=False)
    dc: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    die: Mapped[int] = mapped_column(Integer, nullable=False)  # raw d20, 1-20
    # Character-sheet competence (todo-rpg Phase 1). When a CharacterSheet is in
    # play the GM names the governing ``attribute`` and the engine adds its flat
    # ``modifier`` to ``die`` to get ``total``, classified against ``dc``. With no
    # sheet these default to no attribute / 0 / total == die, preserving the
    # original DC-encodes-competence behavior.
    attribute: Mapped[str | None] = mapped_column(String(20), nullable=True)
    modifier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)  # die + modifier
    # success | failure | critical_success
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)

    session: Mapped[Session] = relationship(back_populates="dice_rolls")


class CharacterSheet(TimestampMixin, Base):
    """Persistent mechanical state for the character in one chronicle (todo-rpg
    Phase 1 — the keystone). One row per :class:`Session`.

    Light, custom system (not 5e): the four attributes are **flat modifiers** —
    the stored integer is added directly to a d20 skill check. Competence lives
    here; the GM-chosen DC encodes task difficulty. ``xp`` accrues from successful
    checks and quest completions; crossing the level curve bumps ``level`` and one
    attribute (todo-rpg Phase 2). Engine owns all the math (LLM only proposes
    deltas). Per-chronicle by design — the reusable ``CharacterCard`` stays a
    narrative template. Gated behind ``CHARACTER_SHEET_ENABLED``.
    """

    __tablename__ = "character_sheets"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_character_sheet_session"),
        _id_check("character_sheets"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    might: Mapped[int] = mapped_column(Integer, nullable=False)
    finesse: Mapped[int] = mapped_column(Integer, nullable=False)
    wits: Mapped[int] = mapped_column(Integer, nullable=False)
    presence: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    session: Mapped[Session] = relationship(back_populates="character_sheet")


class RelationshipState(TimestampMixin, Base):
    __tablename__ = "relationship_states"
    __table_args__ = (_id_check("relationship_states"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False)
    target_entity: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5, index=True, nullable=False)
    last_observed_turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("turns.id", ondelete="SET NULL"), nullable=True
    )

    session: Mapped[Session] = relationship(back_populates="relationship_states")
