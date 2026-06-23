from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DiceRoll,
    EpisodeSummary,
    MemoryFact,
    Quest,
    RelationshipState,
    Turn,
    WorldStateLedger,
)
from app.models import (
    Session as ChatSession,
)
from app.services.fork import ForkService
from tests.factories import (
    EpisodeSummaryFactory,
    MemoryFactFactory,
    QuestFactory,
    SessionFactory,
    TurnFactory,
)

EMBEDDING_DIM = 768


async def _build_parent(db: AsyncSession) -> tuple[ChatSession, dict[int, Turn]]:
    """A parent chronicle with 4 turns and state spread across the fork point (2)."""
    parent = SessionFactory(turn_count=4, last_summarized_turn=2, current_location="Tavern")
    turns = {i: TurnFactory(session=parent, turn_index=i, content=f"turn {i}") for i in range(1, 5)}
    # Flush so parent.id / turn ids (Python-side defaults applied at insert) exist
    # before rows below reference them.
    await db.flush()

    # facts: one from a kept turn, one from a dropped turn, one sourceless
    MemoryFactFactory(session=parent, content="kept fact", source_turn_id=turns[1].id)
    MemoryFactFactory(session=parent, content="dropped fact", source_turn_id=turns[3].id)
    MemoryFactFactory(session=parent, content="sourceless fact", source_turn_id=None)

    # summaries: one fully within range, one beyond it
    EpisodeSummaryFactory(session=parent, start_turn_index=1, end_turn_index=2, content="early")
    EpisodeSummaryFactory(session=parent, start_turn_index=3, end_turn_index=4, content="late")

    # relationships: one observed in a kept turn, one in a dropped turn
    db.add(
        RelationshipState(
            session_id=parent.id,
            source_entity="hero",
            target_entity="maren",
            status="trusted",
            last_observed_turn_id=turns[1].id,
        )
    )
    db.add(
        RelationshipState(
            session_id=parent.id,
            source_entity="hero",
            target_entity="villain",
            status="hostile",
            last_observed_turn_id=turns[3].id,
        )
    )

    # ledger: v1 produced at kept turn, v2 at dropped turn
    db.add(WorldStateLedger(session_id=parent.id, version=1, turn_id=turns[1].id, state={"location": "Tavern"}))
    db.add(WorldStateLedger(session_id=parent.id, version=2, turn_id=turns[3].id, state={"location": "Forest"}))

    # quests: one created before the fork point, one after
    QuestFactory(session=parent, slug="early-quest", created_turn=1)
    QuestFactory(session=parent, slug="late-quest", created_turn=3)

    await db.flush()
    return parent, turns


# ---------------------------------------------------------------------------
# Service-level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_copies_state_up_to_turn(db_session: AsyncSession) -> None:
    parent, _ = await _build_parent(db_session)
    fork = await ForkService.fork_session(db_session, parent, at_turn=2)

    assert fork.id != parent.id
    assert fork.parent_session_id == parent.id
    assert fork.forked_at_turn == 2
    assert fork.turn_count == 2
    assert fork.last_summarized_turn == 2
    assert fork.current_location == "Tavern"

    turns = (await db_session.scalars(select(Turn).where(Turn.session_id == fork.id))).all()
    assert sorted(t.turn_index for t in turns) == [1, 2]

    facts = (await db_session.scalars(select(MemoryFact).where(MemoryFact.session_id == fork.id))).all()
    assert {f.content for f in facts} == {"kept fact", "sourceless fact"}

    summaries = (await db_session.scalars(select(EpisodeSummary).where(EpisodeSummary.session_id == fork.id))).all()
    assert {s.content for s in summaries} == {"early"}

    rels = (await db_session.scalars(select(RelationshipState).where(RelationshipState.session_id == fork.id))).all()
    assert {r.target_entity for r in rels} == {"maren", "villain"}  # both copied (cumulative)

    quests = (await db_session.scalars(select(Quest).where(Quest.session_id == fork.id))).all()
    assert {q.slug for q in quests} == {"early-quest"}


@pytest.mark.asyncio
async def test_fork_remaps_turn_references(db_session: AsyncSession) -> None:
    parent, _ = await _build_parent(db_session)
    fork = await ForkService.fork_session(db_session, parent, at_turn=2)

    fork_turn_ids = {t.id for t in (await db_session.scalars(select(Turn).where(Turn.session_id == fork.id))).all()}

    # ledger version current at N copied as version 1, pointing at a fork turn
    ledgers = (await db_session.scalars(select(WorldStateLedger).where(WorldStateLedger.session_id == fork.id))).all()
    assert len(ledgers) == 1
    assert ledgers[0].version == 1
    assert ledgers[0].state == {"location": "Tavern"}
    assert ledgers[0].turn_id in fork_turn_ids

    # the kept fact's source_turn_id is remapped to a fork turn (not a parent turn)
    kept = await db_session.scalar(
        select(MemoryFact).where(MemoryFact.session_id == fork.id, MemoryFact.content == "kept fact")
    )
    assert kept.source_turn_id in fork_turn_ids

    # relationship observed in a dropped turn loses its reference; kept one is remapped
    rel_rows = (
        await db_session.scalars(select(RelationshipState).where(RelationshipState.session_id == fork.id))
    ).all()
    rels = {r.target_entity: r for r in rel_rows}
    assert rels["maren"].last_observed_turn_id in fork_turn_ids
    assert rels["villain"].last_observed_turn_id is None


@pytest.mark.asyncio
async def test_fork_copies_dice_rolls_on_kept_turns(db_session: AsyncSession) -> None:
    parent = SessionFactory(turn_count=4)
    turns = {i: TurnFactory(session=parent, turn_index=i, content=f"turn {i}") for i in range(1, 5)}
    await db_session.flush()
    # one roll on a kept turn (≤2), one on a dropped turn (>2)
    db_session.add(
        DiceRoll(session_id=parent.id, turn_id=turns[1].id, skill_label="Stealth", dc=12, die=8, outcome="failure")
    )
    db_session.add(
        DiceRoll(session_id=parent.id, turn_id=turns[4].id, skill_label="Athletics", dc=15, die=18, outcome="success")
    )
    await db_session.flush()

    fork = await ForkService.fork_session(db_session, parent, at_turn=2)

    fork_turn_ids = {t.id for t in (await db_session.scalars(select(Turn).where(Turn.session_id == fork.id))).all()}
    rolls = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == fork.id))).all()
    assert len(rolls) == 1  # only the kept-turn roll
    assert rolls[0].skill_label == "Stealth"
    assert rolls[0].turn_id in fork_turn_ids  # remapped to a fork turn


@pytest.mark.asyncio
async def test_fork_leaves_parent_untouched(db_session: AsyncSession) -> None:
    parent, _ = await _build_parent(db_session)
    await ForkService.fork_session(db_session, parent, at_turn=2)

    parent_turns = (await db_session.scalars(select(Turn).where(Turn.session_id == parent.id))).all()
    assert len(parent_turns) == 4
    parent_quests = (await db_session.scalars(select(Quest).where(Quest.session_id == parent.id))).all()
    assert len(parent_quests) == 2
    assert parent.turn_count == 4


@pytest.mark.asyncio
async def test_fork_inside_summarized_block_resets_watermark(db_session: AsyncSession) -> None:
    """Forking mid-summary must not claim uncovered turns are summarized, or the
    fork would never summarize them (regression for the watermark bug)."""
    parent = SessionFactory(turn_count=6, last_summarized_turn=6)
    for i in range(1, 7):
        TurnFactory(session=parent, turn_index=i)
    await db_session.flush()
    # One summary covers turns 1-6; the parent watermark is 6.
    EpisodeSummaryFactory(session=parent, start_turn_index=1, end_turn_index=6, content="all six")
    await db_session.flush()

    fork = await ForkService.fork_session(db_session, parent, at_turn=4)

    # The 1-6 summary straddles the fork point (6 > 4) → dropped. The watermark
    # must fall back to 0 (nothing copied), not the parent's 6 or at_turn 4.
    copied = (await db_session.scalars(select(EpisodeSummary).where(EpisodeSummary.session_id == fork.id))).all()
    assert copied == []
    assert fork.last_summarized_turn == 0


@pytest.mark.asyncio
async def test_fork_deepcopies_json_columns(db_session: AsyncSession) -> None:
    """The fork must not share mutable JSON objects with the parent."""
    parent, _ = await _build_parent(db_session)
    fork = await ForkService.fork_session(db_session, parent, at_turn=2)

    parent_ledger = await db_session.scalar(
        select(WorldStateLedger).where(WorldStateLedger.session_id == parent.id, WorldStateLedger.version == 1)
    )
    fork_ledger = await db_session.scalar(select(WorldStateLedger).where(WorldStateLedger.session_id == fork.id))
    assert fork_ledger.state == parent_ledger.state
    assert fork_ledger.state is not parent_ledger.state  # deep-copied, not aliased

    parent_quest = await db_session.scalar(
        select(Quest).where(Quest.session_id == parent.id, Quest.slug == "early-quest")
    )
    fork_quest = await db_session.scalar(select(Quest).where(Quest.session_id == fork.id, Quest.slug == "early-quest"))
    assert fork_quest.stages == parent_quest.stages
    assert fork_quest.stages is not parent_quest.stages


@pytest.mark.asyncio
async def test_ledger_at_skips_unplaceable_null_turn_row(db_session: AsyncSession) -> None:
    """A higher-version NULL-turn_id ledger row must not seed the fork (it can't
    be proven to predate the fork point); the latest kept turn-tied row wins."""
    parent = SessionFactory(turn_count=3)
    turns = {i: TurnFactory(session=parent, turn_index=i) for i in range(1, 4)}
    await db_session.flush()
    db_session.add(WorldStateLedger(session_id=parent.id, version=1, turn_id=turns[2].id, state={"loc": "at turn 2"}))
    # A later, turn-less edit (e.g. manual) — unplaceable relative to the fork point.
    db_session.add(WorldStateLedger(session_id=parent.id, version=2, turn_id=None, state={"loc": "manual edit"}))
    await db_session.flush()

    fork = await ForkService.fork_session(db_session, parent, at_turn=2)

    led = (await db_session.scalars(select(WorldStateLedger).where(WorldStateLedger.session_id == fork.id))).all()
    assert len(led) == 1
    assert led[0].state == {"loc": "at turn 2"}  # NOT the v2 NULL-turn "manual edit"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_endpoint_creates_fork(async_client: AsyncClient, db_session: AsyncSession) -> None:
    parent, _ = await _build_parent(db_session)
    resp = await async_client.post(f"/session/{parent.id}/fork", json={"at_turn": 2, "title": "My Fork"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Fork"
    assert data["parent_session_id"] == parent.id
    assert data["forked_at_turn"] == 2
    assert data["turn_count"] == 2
    assert data["id"] != parent.id


@pytest.mark.asyncio
async def test_fork_endpoint_defaults_to_whole_chronicle(async_client: AsyncClient, db_session: AsyncSession) -> None:
    parent, _ = await _build_parent(db_session)
    resp = await async_client.post(f"/session/{parent.id}/fork", json={})
    assert resp.status_code == 201
    assert resp.json()["forked_at_turn"] == 4


@pytest.mark.asyncio
async def test_fork_endpoint_rejects_out_of_range_turn(async_client: AsyncClient, db_session: AsyncSession) -> None:
    parent, _ = await _build_parent(db_session)
    resp = await async_client.post(f"/session/{parent.id}/fork", json={"at_turn": 99})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fork_endpoint_404_for_missing_session(async_client: AsyncClient) -> None:
    resp = await async_client.post("/session/does-not-exist/fork", json={"at_turn": 1})
    assert resp.status_code == 404
