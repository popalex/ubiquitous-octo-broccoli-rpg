from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest.mark.asyncio
async def test_character_card_round_trip(db_session: AsyncSession) -> None:
    char = CharacterCardFactory(
        name="Elara Swiftblade",
        description="An elven ranger.",
        hard_rules="No firearms.",
        style_guide="Poetic and concise.",
    )
    await db_session.flush()
    char_id = char.id
    db_session.expire(char)

    loaded = await db_session.get(CharacterCard, char_id)
    assert loaded is not None
    assert loaded.name == "Elara Swiftblade"
    assert loaded.description == "An elven ranger."
    assert loaded.hard_rules == "No firearms."
    assert loaded.style_guide == "Poetic and concise."


# ===========================================================================
# WorldState
# ===========================================================================


@pytest.mark.asyncio
async def test_world_state_round_trip(db_session: AsyncSession) -> None:
    world = WorldStateFactory(
        name="Aethoria",
        description="A floating realm.",
        canon="Magic flows from leylines.",
        hard_rules="No anachronisms.",
    )
    await db_session.flush()
    world_id = world.id
    db_session.expire(world)

    loaded = await db_session.get(WorldState, world_id)
    assert loaded is not None
    assert loaded.name == "Aethoria"
    assert loaded.canon == "Magic flows from leylines."


# ===========================================================================
# Session — cascade delete on turns
# ===========================================================================


@pytest.mark.asyncio
async def test_session_cascades_to_turns_on_delete(db_session: AsyncSession) -> None:
    session = SessionFactory()
    TurnFactory(session=session, turn_index=1)
    TurnFactory(session=session, turn_index=2)
    await db_session.flush()

    # Verify turns exist
    turns_before = (await db_session.scalars(select(Turn).where(Turn.session_id == session.id))).all()
    assert len(turns_before) == 2

    await db_session.delete(session)
    await db_session.flush()

    turns_after = (await db_session.scalars(select(Turn).where(Turn.session_id == session.id))).all()
    assert len(turns_after) == 0


# ===========================================================================
# Turn — unique constraint on (session_id, turn_index)
# ===========================================================================


@pytest.mark.asyncio
async def test_turn_unique_constraint_on_session_and_index(db_session: AsyncSession) -> None:
    session = SessionFactory()
    TurnFactory(session=session, turn_index=1)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        TurnFactory(session=session, turn_index=1)
        await db_session.flush()


# ===========================================================================
# MemoryFact — stores and retrieves pgvector embedding
# ===========================================================================


@pytest.mark.asyncio
async def test_memory_fact_stores_and_retrieves_embedding(db_session: AsyncSession) -> None:
    embedding = [float(i) / EMBEDDING_DIM for i in range(EMBEDDING_DIM)]
    fact = MemoryFactFactory(
        content="The sword is enchanted.",
        importance=0.9,
        embedding=embedding,
    )
    await db_session.flush()
    fact_id = fact.id
    db_session.expire(fact)

    loaded = await db_session.get(MemoryFact, fact_id)
    assert loaded is not None
    assert loaded.content == "The sword is enchanted."
    assert loaded.importance == pytest.approx(0.9)
    assert len(loaded.embedding) == EMBEDDING_DIM


# ===========================================================================
# EpisodeSummary — stores and retrieves pgvector embedding
# ===========================================================================


@pytest.mark.asyncio
async def test_episode_summary_stores_and_retrieves_embedding(db_session: AsyncSession) -> None:
    embedding = [0.5] * EMBEDDING_DIM
    summary = EpisodeSummaryFactory(
        content="The party explored the ruins.",
        importance=0.7,
        embedding=embedding,
    )
    await db_session.flush()
    summary_id = summary.id
    db_session.expire(summary)

    loaded = await db_session.get(EpisodeSummary, summary_id)
    assert loaded is not None
    assert loaded.content == "The party explored the ruins."
    assert len(loaded.embedding) == EMBEDDING_DIM


# ===========================================================================
# RelationshipState — links source/target entities correctly
# ===========================================================================


@pytest.mark.asyncio
async def test_relationship_state_links_entities(db_session: AsyncSession) -> None:
    session = SessionFactory()
    await db_session.flush()
    rel = RelationshipState(
        session_id=session.id,
        source_entity="Aria",
        target_entity="Dark Lord",
        status="rivals",
        notes="Long rivalry dating back to the siege.",
        importance=0.85,
    )
    db_session.add(rel)
    await db_session.flush()
    rel_id = rel.id
    db_session.expire(rel)

    loaded = await db_session.get(RelationshipState, rel_id)
    assert loaded is not None
    assert loaded.source_entity == "Aria"
    assert loaded.target_entity == "Dark Lord"
    assert loaded.status == "rivals"
    assert loaded.importance == pytest.approx(0.85)


# ===========================================================================
# TimestampMixin — auto-sets created_at and updated_at
# ===========================================================================


@pytest.mark.asyncio
async def test_timestamp_mixin_auto_sets_created_at_and_updated_at(db_session: AsyncSession) -> None:
    char = CharacterCardFactory()
    await db_session.flush()
    char_id = char.id
    db_session.expire(char)

    loaded = await db_session.get(CharacterCard, char_id)
    assert loaded is not None
    assert isinstance(loaded.created_at, datetime)
    assert isinstance(loaded.updated_at, datetime)
    # Both should be recent (within the last minute)
    now = datetime.now(UTC)
    age_seconds = abs((now - loaded.created_at.replace(tzinfo=UTC)).total_seconds())
    assert age_seconds < 60
