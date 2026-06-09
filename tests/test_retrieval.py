from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.services.retrieval import RetrievalService
from tests.conftest import MockProvider, make_test_settings
from tests.factories import EpisodeSummaryFactory, MemoryFactFactory, SessionFactory

EMBEDDING_DIM = 768


@pytest.fixture()
def service(mock_provider: MockProvider) -> RetrievalService:
    return RetrievalService(mock_provider, make_test_settings())


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_memories(
    service: RetrievalService, db_session: Session
) -> None:
    session = SessionFactory()
    db_session.flush()

    results = await service.retrieve(db_session, session, "What happened?")
    assert results == []


@pytest.mark.asyncio
async def test_returns_facts_ranked_by_weighted_score(
    service: RetrievalService, db_session: Session
) -> None:
    session = SessionFactory()
    # Low-importance fact
    MemoryFactFactory(session=session, content="Minor detail.", importance=0.1)
    # High-importance fact
    MemoryFactFactory(session=session, content="Hero defeated the dragon.", importance=0.9)
    db_session.flush()

    results = await service.retrieve(db_session, session, "dragon fight")
    assert len(results) >= 2
    # Verify they are sorted descending by weighted_score
    scores = [r.weighted_score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_returns_episode_summaries_alongside_facts(
    service: RetrievalService, db_session: Session
) -> None:
    session = SessionFactory()
    MemoryFactFactory(session=session, content="A fact.")
    EpisodeSummaryFactory(session=session, content="A summary.")
    db_session.flush()

    results = await service.retrieve(db_session, session, "recent events")
    kinds = {r.kind for r in results}
    assert "fact" in kinds
    assert "summary" in kinds


@pytest.mark.asyncio
async def test_respects_retrieval_top_k(
    db_session: Session, mock_provider: MockProvider
) -> None:
    settings = make_test_settings(retrieval_top_k=2, retrieval_candidate_pool=20)
    service = RetrievalService(mock_provider, settings)

    session = SessionFactory()
    for i in range(5):
        MemoryFactFactory(session=session, content=f"Fact {i}.", importance=0.5)
    db_session.flush()

    results = await service.retrieve(db_session, session, "anything")
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_recency_scoring_decays_older_memories(
    db_session: Session, mock_provider: MockProvider
) -> None:
    settings = make_test_settings(recency_half_life_hours=72)
    service = RetrievalService(mock_provider, settings)

    session = SessionFactory()
    recent_fact = MemoryFactFactory(session=session, content="Recent event.", importance=0.5)
    old_fact = MemoryFactFactory(session=session, content="Old event.", importance=0.5)
    db_session.flush()

    # Manually patch created_at on old_fact to be 200 hours ago
    old_time = datetime.now(UTC) - timedelta(hours=200)
    db_session.execute(
        __import__("sqlalchemy").text("UPDATE memory_facts SET created_at = :ts WHERE id = :id"),
        {"ts": old_time, "id": old_fact.id},
    )
    db_session.flush()
    # Expire the ORM identity-map entry so the SELECT in retrieve() re-reads from DB
    db_session.expire(old_fact)

    results = await service.retrieve(db_session, session, "event")
    result_map = {r.id: r for r in results}
    assert result_map[recent_fact.id].recency_score > result_map[old_fact.id].recency_score


@pytest.mark.asyncio
async def test_importance_score_contributes_to_ranking(
    service: RetrievalService, db_session: Session
) -> None:
    session = SessionFactory()
    low = MemoryFactFactory(session=session, content="Low importance.", importance=0.1)
    high = MemoryFactFactory(session=session, content="High importance.", importance=1.0)
    db_session.flush()

    results = await service.retrieve(db_session, session, "importance check")
    result_map = {r.id: r for r in results}
    assert result_map[high.id].importance > result_map[low.id].importance


@pytest.mark.asyncio
async def test_mixed_facts_and_summaries_merged_and_sorted(
    service: RetrievalService, db_session: Session
) -> None:
    session = SessionFactory()
    MemoryFactFactory(session=session, content="Fact A.", importance=0.6)
    MemoryFactFactory(session=session, content="Fact B.", importance=0.4)
    EpisodeSummaryFactory(session=session, content="Summary A.", importance=0.8)
    EpisodeSummaryFactory(session=session, content="Summary B.", importance=0.3)
    db_session.flush()

    results = await service.retrieve(db_session, session, "anything")
    scores = [r.weighted_score for r in results]
    assert scores == sorted(scores, reverse=True)
    kinds = [r.kind for r in results]
    assert "fact" in kinds
    assert "summary" in kinds
