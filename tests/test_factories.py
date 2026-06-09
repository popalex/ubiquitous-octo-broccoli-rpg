from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CharacterCard,
    EpisodeSummary,
    MemoryFact,
    Turn,
    WorldState,
)
from app.models import (
    Session as ChatSession,
)
from tests.factories import (
    CharacterCardFactory,
    EpisodeSummaryFactory,
    MemoryFactFactory,
    SessionFactory,
    TurnFactory,
    WorldStateFactory,
)

# ===========================================================================
# Each factory creates a valid persisted row
# ===========================================================================


@pytest.mark.asyncio
async def test_character_card_factory_creates_persisted_row(db_session: AsyncSession) -> None:
    char = CharacterCardFactory()
    await db_session.flush()
    loaded = await db_session.get(CharacterCard, char.id)
    assert loaded is not None
    assert loaded.name == char.name


@pytest.mark.asyncio
async def test_world_state_factory_creates_persisted_row(db_session: AsyncSession) -> None:
    world = WorldStateFactory()
    await db_session.flush()
    loaded = await db_session.get(WorldState, world.id)
    assert loaded is not None
    assert loaded.name == world.name


@pytest.mark.asyncio
async def test_session_factory_creates_persisted_row(db_session: AsyncSession) -> None:
    session = SessionFactory()
    await db_session.flush()
    loaded = await db_session.get(ChatSession, session.id)
    assert loaded is not None
    assert loaded.title == session.title


@pytest.mark.asyncio
async def test_turn_factory_creates_persisted_row(db_session: AsyncSession) -> None:
    turn = TurnFactory()
    await db_session.flush()
    loaded = await db_session.get(Turn, turn.id)
    assert loaded is not None
    assert loaded.content == turn.content


@pytest.mark.asyncio
async def test_memory_fact_factory_creates_persisted_row(db_session: AsyncSession) -> None:
    fact = MemoryFactFactory()
    await db_session.flush()
    loaded = await db_session.get(MemoryFact, fact.id)
    assert loaded is not None
    assert loaded.content == fact.content


@pytest.mark.asyncio
async def test_episode_summary_factory_creates_persisted_row(db_session: AsyncSession) -> None:
    summary = EpisodeSummaryFactory()
    await db_session.flush()
    loaded = await db_session.get(EpisodeSummary, summary.id)
    assert loaded is not None
    assert loaded.content == summary.content


# ===========================================================================
# SubFactory relationships are wired correctly
# ===========================================================================


@pytest.mark.asyncio
async def test_session_factory_subfactory_wires_character_and_world(db_session: AsyncSession) -> None:
    session = SessionFactory()
    await db_session.flush()

    loaded = await db_session.get(ChatSession, session.id)
    assert loaded is not None
    assert loaded.character_card_id is not None
    assert loaded.world_state_id is not None

    char = await db_session.get(CharacterCard, loaded.character_card_id)
    world = await db_session.get(WorldState, loaded.world_state_id)
    assert char is not None
    assert world is not None


@pytest.mark.asyncio
async def test_turn_factory_subfactory_wires_session(db_session: AsyncSession) -> None:
    turn = TurnFactory()
    await db_session.flush()

    loaded = await db_session.get(Turn, turn.id)
    assert loaded is not None
    assert loaded.session_id is not None

    session = await db_session.get(ChatSession, loaded.session_id)
    assert session is not None


@pytest.mark.asyncio
async def test_memory_fact_factory_subfactory_wires_session(db_session: AsyncSession) -> None:
    fact = MemoryFactFactory()
    await db_session.flush()

    loaded = await db_session.get(MemoryFact, fact.id)
    assert loaded is not None
    assert loaded.session_id is not None

    session = await db_session.get(ChatSession, loaded.session_id)
    assert session is not None


@pytest.mark.asyncio
async def test_episode_summary_factory_subfactory_wires_session(db_session: AsyncSession) -> None:
    summary = EpisodeSummaryFactory()
    await db_session.flush()

    loaded = await db_session.get(EpisodeSummary, summary.id)
    assert loaded is not None
    assert loaded.session_id is not None

    session = await db_session.get(ChatSession, loaded.session_id)
    assert session is not None


# ===========================================================================
# Sequence fields produce unique values across multiple creates
# ===========================================================================


@pytest.mark.asyncio
async def test_character_card_names_are_unique_across_creates(db_session: AsyncSession) -> None:
    chars = [CharacterCardFactory() for _ in range(3)]
    await db_session.flush()
    names = [c.name for c in chars]
    assert len(set(names)) == 3


@pytest.mark.asyncio
async def test_world_state_names_are_unique_across_creates(db_session: AsyncSession) -> None:
    worlds = [WorldStateFactory() for _ in range(3)]
    await db_session.flush()
    names = [w.name for w in worlds]
    assert len(set(names)) == 3


@pytest.mark.asyncio
async def test_session_titles_are_unique_across_creates(db_session: AsyncSession) -> None:
    sessions = [SessionFactory() for _ in range(3)]
    await db_session.flush()
    titles = [s.title for s in sessions]
    assert len(set(titles)) == 3
