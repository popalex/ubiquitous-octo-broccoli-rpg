from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CharacterCard,
    EpisodeSummary,
    MemoryFact,
    RelationshipState,
    Turn,
    WorldState,
)
from tests.factories import (
    CharacterCardFactory,
    EpisodeSummaryFactory,
    MemoryFactFactory,
    SessionFactory,
    TurnFactory,
    WorldStateFactory,
)

EMBEDDING_DIM = 768


# ===========================================================================
# CharacterCard
# ===========================================================================


def test_character_card_round_trip(db_session: Session) -> None:
    char = CharacterCardFactory(
        name="Elara Swiftblade",
        description="An elven ranger.",
        hard_rules="No firearms.",
        style_guide="Poetic and concise.",
    )
    db_session.flush()
    db_session.expire(char)

    loaded = db_session.get(CharacterCard, char.id)
    assert loaded is not None
    assert loaded.name == "Elara Swiftblade"
    assert loaded.description == "An elven ranger."
    assert loaded.hard_rules == "No firearms."
    assert loaded.style_guide == "Poetic and concise."


# ===========================================================================
# WorldState
# ===========================================================================


def test_world_state_round_trip(db_session: Session) -> None:
    world = WorldStateFactory(
        name="Aethoria",
        description="A floating realm.",
        canon="Magic flows from leylines.",
        hard_rules="No anachronisms.",
    )
    db_session.flush()
    db_session.expire(world)

    loaded = db_session.get(WorldState, world.id)
    assert loaded is not None
    assert loaded.name == "Aethoria"
    assert loaded.canon == "Magic flows from leylines."


# ===========================================================================
# Session — cascade delete on turns
# ===========================================================================


def test_session_cascades_to_turns_on_delete(db_session: Session) -> None:
    session = SessionFactory()
    TurnFactory(session=session, turn_index=1)
    TurnFactory(session=session, turn_index=2)
    db_session.flush()

    # Verify turns exist
    turns_before = db_session.scalars(
        select(Turn).where(Turn.session_id == session.id)
    ).all()
    assert len(turns_before) == 2

    db_session.delete(session)
    db_session.flush()

    turns_after = db_session.scalars(
        select(Turn).where(Turn.session_id == session.id)
    ).all()
    assert len(turns_after) == 0


# ===========================================================================
# Turn — unique constraint on (session_id, turn_index)
# ===========================================================================


def test_turn_unique_constraint_on_session_and_index(db_session: Session) -> None:
    session = SessionFactory()
    TurnFactory(session=session, turn_index=1)
    db_session.flush()

    with pytest.raises(IntegrityError):
        TurnFactory(session=session, turn_index=1)
        db_session.flush()


# ===========================================================================
# MemoryFact — stores and retrieves pgvector embedding
# ===========================================================================


def test_memory_fact_stores_and_retrieves_embedding(db_session: Session) -> None:
    embedding = [float(i) / EMBEDDING_DIM for i in range(EMBEDDING_DIM)]
    fact = MemoryFactFactory(
        content="The sword is enchanted.",
        importance=0.9,
        embedding=embedding,
    )
    db_session.flush()
    db_session.expire(fact)

    loaded = db_session.get(MemoryFact, fact.id)
    assert loaded is not None
    assert loaded.content == "The sword is enchanted."
    assert loaded.importance == pytest.approx(0.9)
    assert len(loaded.embedding) == EMBEDDING_DIM


# ===========================================================================
# EpisodeSummary — stores and retrieves pgvector embedding
# ===========================================================================


def test_episode_summary_stores_and_retrieves_embedding(db_session: Session) -> None:
    embedding = [0.5] * EMBEDDING_DIM
    summary = EpisodeSummaryFactory(
        content="The party explored the ruins.",
        importance=0.7,
        embedding=embedding,
    )
    db_session.flush()
    db_session.expire(summary)

    loaded = db_session.get(EpisodeSummary, summary.id)
    assert loaded is not None
    assert loaded.content == "The party explored the ruins."
    assert len(loaded.embedding) == EMBEDDING_DIM


# ===========================================================================
# RelationshipState — links source/target entities correctly
# ===========================================================================


def test_relationship_state_links_entities(db_session: Session) -> None:
    session = SessionFactory()
    rel = RelationshipState(
        session_id=session.id,
        source_entity="Aria",
        target_entity="Dark Lord",
        status="rivals",
        notes="Long rivalry dating back to the siege.",
        importance=0.85,
    )
    db_session.add(rel)
    db_session.flush()
    db_session.expire(rel)

    loaded = db_session.get(RelationshipState, rel.id)
    assert loaded is not None
    assert loaded.source_entity == "Aria"
    assert loaded.target_entity == "Dark Lord"
    assert loaded.status == "rivals"
    assert loaded.importance == pytest.approx(0.85)


# ===========================================================================
# TimestampMixin — auto-sets created_at and updated_at
# ===========================================================================


def test_timestamp_mixin_auto_sets_created_at_and_updated_at(db_session: Session) -> None:
    char = CharacterCardFactory()
    db_session.flush()
    db_session.expire(char)

    loaded = db_session.get(CharacterCard, char.id)
    assert loaded is not None
    assert isinstance(loaded.created_at, datetime)
    assert isinstance(loaded.updated_at, datetime)
    # Both should be recent (within the last minute)
    now = datetime.now(UTC)
    age_seconds = abs((now - loaded.created_at.replace(tzinfo=UTC)).total_seconds())
    assert age_seconds < 60
