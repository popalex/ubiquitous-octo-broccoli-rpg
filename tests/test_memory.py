from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EpisodeSummary, MemoryFact, RelationshipState
from app.services.memory import MemoryRefreshResult, MemoryService
from app.providers.base import ProviderError
from tests.conftest import MockProvider, make_test_settings
from tests.factories import SessionFactory, TurnFactory

EMBEDDING_DIM = 768


def _make_service(mock_provider: MockProvider, **setting_overrides) -> MemoryService:
    settings = make_test_settings(**setting_overrides)
    return MemoryService(mock_provider, mock_provider, settings)


# ---------------------------------------------------------------------------
# maybe_refresh — no-op below threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_refresh_noop_below_interval(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=5, last_summarized_turn=0)
    db_session.flush()

    result = await service.maybe_refresh(db_session, session)
    assert result == MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)


# ---------------------------------------------------------------------------
# maybe_refresh — creates EpisodeSummary at threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_refresh_creates_episode_summary(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    mock_provider.set_json_response({
        "summary": "The hero ventured forth.",
        "importance": 0.7,
        "facts": [],
        "relationships": [],
    })

    result = await service.maybe_refresh(db_session, session)
    assert result.summary_created is True

    summaries = db_session.scalars(
        select(EpisodeSummary).where(EpisodeSummary.session_id == session.id)
    ).all()
    assert len(summaries) == 1
    assert summaries[0].content == "The hero ventured forth."


# ---------------------------------------------------------------------------
# maybe_refresh — extracts and persists MemoryFacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_refresh_extracts_memory_facts(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    mock_provider.set_json_response({
        "summary": "Summary.",
        "importance": 0.5,
        "facts": [
            {"content": "The dragon is dead.", "importance": 0.9},
            {"content": "The sword was found.", "importance": 0.7},
        ],
        "relationships": [],
    })

    result = await service.maybe_refresh(db_session, session)
    assert result.facts_written == 2

    facts = db_session.scalars(
        select(MemoryFact).where(MemoryFact.session_id == session.id)
    ).all()
    assert len(facts) == 2
    contents = {f.content for f in facts}
    assert "The dragon is dead." in contents
    assert "The sword was found." in contents


# ---------------------------------------------------------------------------
# maybe_refresh — creates RelationshipState entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_refresh_creates_relationships(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    mock_provider.set_json_response({
        "summary": "Summary.",
        "importance": 0.5,
        "facts": [],
        "relationships": [
            {
                "source_entity": "Hero",
                "target_entity": "Dragon",
                "status": "enemies",
                "notes": "Long-standing rivalry",
                "importance": 0.8,
            }
        ],
    })

    result = await service.maybe_refresh(db_session, session)
    assert result.relationships_written == 1

    rels = db_session.scalars(
        select(RelationshipState).where(RelationshipState.session_id == session.id)
    ).all()
    assert len(rels) == 1
    assert rels[0].source_entity == "Hero"
    assert rels[0].target_entity == "Dragon"
    assert rels[0].status == "enemies"


# ---------------------------------------------------------------------------
# Embeddings generated for new facts and summaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embeddings_generated_for_facts_and_summaries(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    mock_provider.set_json_response({
        "summary": "Summary text.",
        "importance": 0.5,
        "facts": [{"content": "Fact text.", "importance": 0.6}],
        "relationships": [],
    })

    embed_calls: list[list[str]] = []
    original_embed = mock_provider.embed_texts

    async def tracking_embed(texts):
        embed_calls.append(list(texts))
        return await original_embed(texts)

    mock_provider.embed_texts = tracking_embed
    await service.maybe_refresh(db_session, session)

    all_embedded_texts = [t for batch in embed_calls for t in batch]
    assert "Summary text." in all_embedded_texts
    assert "Fact text." in all_embedded_texts


# ---------------------------------------------------------------------------
# last_summarized_turn advanced after refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_summarized_turn_advanced_after_refresh(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    mock_provider.set_json_response({
        "summary": "Summary.",
        "importance": 0.5,
        "facts": [],
        "relationships": [],
    })

    await service.maybe_refresh(db_session, session)
    assert session.last_summarized_turn == 6


# ---------------------------------------------------------------------------
# MemoryRefreshResult reports correct counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_refresh_result_correct_counts(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    mock_provider.set_json_response({
        "summary": "Summary.",
        "importance": 0.5,
        "facts": [
            {"content": "Fact one.", "importance": 0.5},
        ],
        "relationships": [
            {
                "source_entity": "A",
                "target_entity": "B",
                "status": "allies",
                "importance": 0.5,
            }
        ],
    })

    result = await service.maybe_refresh(db_session, session)
    assert result.summary_created is True
    assert result.facts_written == 1
    assert result.relationships_written == 1


# ---------------------------------------------------------------------------
# Malformed LLM JSON for facts handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_for_facts_handled_gracefully(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    # facts list contains entries with empty content — should be skipped
    mock_provider.set_json_response({
        "summary": "Valid summary.",
        "importance": 0.5,
        "facts": [
            {"content": "", "importance": 0.5},   # empty, should be skipped
            {"content": "  ", "importance": 0.5},  # whitespace-only, skipped
        ],
        "relationships": [],
    })

    result = await service.maybe_refresh(db_session, session)
    assert result.facts_written == 0
    assert result.summary_created is True


# ---------------------------------------------------------------------------
# Malformed LLM JSON for episode summary handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_for_episode_summary_handled_gracefully(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(memory_summary_interval=6)
    service = MemoryService(mock_provider, mock_provider, settings)
    session = SessionFactory(turn_count=6, last_summarized_turn=0)
    for i in range(1, 7):
        TurnFactory(session=session, turn_index=i, role="user", content=f"Turn {i}")
    db_session.flush()

    # summary field is missing — should fall back to default text
    mock_provider.set_json_response({
        "importance": 0.5,
        "facts": [],
        "relationships": [],
    })

    result = await service.maybe_refresh(db_session, session)
    assert result.summary_created is True
    summaries = db_session.scalars(
        select(EpisodeSummary).where(EpisodeSummary.session_id == session.id)
    ).all()
    assert summaries[0].content == "No summary produced."
