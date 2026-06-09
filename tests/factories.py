from __future__ import annotations

import factory
from factory.alchemy import SQLAlchemyModelFactory

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

EMBEDDING_DIM = 768


class CharacterCardFactory(SQLAlchemyModelFactory):
    class Meta:
        model = CharacterCard
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    name = factory.Sequence(lambda n: f"Character {n}")
    description = "A brave adventurer with a mysterious past."
    hard_rules = "No killing innocents.\nStay in character."
    style_guide = "Be concise and grounded."


class WorldStateFactory(SQLAlchemyModelFactory):
    class Meta:
        model = WorldState
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    name = factory.Sequence(lambda n: f"World {n}")
    description = "A dark fantasy realm plagued by shadow."
    canon = "Magic exists. The old gods are dead."
    hard_rules = "No anachronisms. No modern technology."


class SessionFactory(SQLAlchemyModelFactory):
    class Meta:
        model = ChatSession
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    character_card = factory.SubFactory(CharacterCardFactory)
    world_state = factory.SubFactory(WorldStateFactory)
    title = factory.Sequence(lambda n: f"Test Session {n}")
    status = "active"
    turn_count = 0
    last_summarized_turn = 0
    gm_enabled = False


class TurnFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Turn
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    session = factory.SubFactory(SessionFactory)
    turn_index = factory.Sequence(lambda n: n + 1)
    role = "user"
    content = "Hello, adventurer."
    token_estimate = 10
    turn_type = "chat"


class MemoryFactFactory(SQLAlchemyModelFactory):
    class Meta:
        model = MemoryFact
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    session = factory.SubFactory(SessionFactory)
    content = "The hero defeated the dragon."
    importance = 0.8
    embedding = factory.LazyFunction(lambda: [0.1] * EMBEDDING_DIM)


class EpisodeSummaryFactory(SQLAlchemyModelFactory):
    class Meta:
        model = EpisodeSummary
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    session = factory.SubFactory(SessionFactory)
    start_turn_index = 1
    end_turn_index = 6
    content = "The adventurer explored the dungeon and found a clue."
    importance = 0.7
    embedding = factory.LazyFunction(lambda: [0.1] * EMBEDDING_DIM)
