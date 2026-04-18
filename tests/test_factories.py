from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models import (
    CharacterCard,
    EpisodeSummary,
    MemoryFact,
    Session as ChatSession,
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


# ===========================================================================
# Each factory creates a valid persisted row
# ===========================================================================


def test_character_card_factory_creates_persisted_row(db_session: Session) -> None:
    char = CharacterCardFactory()
    db_session.flush()
    loaded = db_session.get(CharacterCard, char.id)
    assert loaded is not None
    assert loaded.name == char.name


def test_world_state_factory_creates_persisted_row(db_session: Session) -> None:
    world = WorldStateFactory()
    db_session.flush()
    loaded = db_session.get(WorldState, world.id)
    assert loaded is not None
    assert loaded.name == world.name


def test_session_factory_creates_persisted_row(db_session: Session) -> None:
    session = SessionFactory()
    db_session.flush()
    loaded = db_session.get(ChatSession, session.id)
    assert loaded is not None
    assert loaded.title == session.title


def test_turn_factory_creates_persisted_row(db_session: Session) -> None:
    turn = TurnFactory()
    db_session.flush()
    loaded = db_session.get(Turn, turn.id)
    assert loaded is not None
    assert loaded.content == turn.content


def test_memory_fact_factory_creates_persisted_row(db_session: Session) -> None:
    fact = MemoryFactFactory()
    db_session.flush()
    loaded = db_session.get(MemoryFact, fact.id)
    assert loaded is not None
    assert loaded.content == fact.content


def test_episode_summary_factory_creates_persisted_row(db_session: Session) -> None:
    summary = EpisodeSummaryFactory()
    db_session.flush()
    loaded = db_session.get(EpisodeSummary, summary.id)
    assert loaded is not None
    assert loaded.content == summary.content


# ===========================================================================
# SubFactory relationships are wired correctly
# ===========================================================================


def test_session_factory_subfactory_wires_character_and_world(db_session: Session) -> None:
    session = SessionFactory()
    db_session.flush()

    loaded = db_session.get(ChatSession, session.id)
    assert loaded is not None
    assert loaded.character_card_id is not None
    assert loaded.world_state_id is not None

    char = db_session.get(CharacterCard, loaded.character_card_id)
    world = db_session.get(WorldState, loaded.world_state_id)
    assert char is not None
    assert world is not None


def test_turn_factory_subfactory_wires_session(db_session: Session) -> None:
    turn = TurnFactory()
    db_session.flush()

    loaded = db_session.get(Turn, turn.id)
    assert loaded is not None
    assert loaded.session_id is not None

    session = db_session.get(ChatSession, loaded.session_id)
    assert session is not None


def test_memory_fact_factory_subfactory_wires_session(db_session: Session) -> None:
    fact = MemoryFactFactory()
    db_session.flush()

    loaded = db_session.get(MemoryFact, fact.id)
    assert loaded is not None
    assert loaded.session_id is not None

    session = db_session.get(ChatSession, loaded.session_id)
    assert session is not None


def test_episode_summary_factory_subfactory_wires_session(db_session: Session) -> None:
    summary = EpisodeSummaryFactory()
    db_session.flush()

    loaded = db_session.get(EpisodeSummary, summary.id)
    assert loaded is not None
    assert loaded.session_id is not None

    session = db_session.get(ChatSession, loaded.session_id)
    assert session is not None


# ===========================================================================
# Sequence fields produce unique values across multiple creates
# ===========================================================================


def test_character_card_names_are_unique_across_creates(db_session: Session) -> None:
    chars = [CharacterCardFactory() for _ in range(3)]
    db_session.flush()
    names = [c.name for c in chars]
    assert len(set(names)) == 3


def test_world_state_names_are_unique_across_creates(db_session: Session) -> None:
    worlds = [WorldStateFactory() for _ in range(3)]
    db_session.flush()
    names = [w.name for w in worlds]
    assert len(set(names)) == 3


def test_session_titles_are_unique_across_creates(db_session: Session) -> None:
    sessions = [SessionFactory() for _ in range(3)]
    db_session.flush()
    titles = [s.title for s in sessions]
    assert len(set(titles)) == 3
