from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Quest
from app.services.quests import (
    NewQuest,
    QuestDelta,
    QuestService,
    QuestStage,
    QuestUpdateItem,
)
from tests.conftest import MockProvider, make_test_settings
from tests.factories import QuestFactory, SessionFactory


def _service(**setting_overrides) -> QuestService:
    settings = make_test_settings(quests_enabled=True, **setting_overrides)
    return QuestService(MockProvider(settings), settings)


def _quest(**overrides) -> Quest:
    defaults = dict(
        slug="find-marens-sister",
        title="Find Maren's Sister",
        quest_type="promise",
        description="You promised Maren to find her sister.",
        stakes="Maren's sister is lost forever.",
        status="active",
        origin="emergent",
        stages=[{"id": "ask-around", "description": "Ask around the village", "done": False}],
        created_turn=2,
        accepted_turn=2,
        last_progress_turn=2,
        last_escalation_turn=0,
    )
    defaults.update(overrides)
    return Quest(**defaults)


# ---------------------------------------------------------------------------
# apply_delta — new quests
# ---------------------------------------------------------------------------


def test_apply_delta_creates_emergent_quest() -> None:
    svc = _service()
    delta = QuestDelta(
        quests_new=[
            NewQuest(
                slug="find-marens-sister",
                title="Find Maren's Sister",
                quest_type="promise",
                description="You promised Maren to find her sister.",
                stakes="She is lost forever.",
                stages=[QuestStage(id="ask-around", description="Ask around")],
            )
        ]
    )
    changes = svc.apply_delta([], delta, turn_count=4)
    assert len(changes) == 1
    quest = changes[0].quest
    assert changes[0].change == "started"
    # Emergent quests are player commitments — already active and accepted.
    assert quest.status == "active"
    assert quest.accepted_turn == 4
    assert quest.last_progress_turn == 4
    assert quest.stages[0]["done"] is False


def test_apply_delta_skips_duplicate_slug() -> None:
    svc = _service()
    existing = _quest()
    delta = QuestDelta(
        quests_new=[NewQuest(slug=existing.slug, title="Dup", description="dup")]
    )
    changes = svc.apply_delta([existing], delta, turn_count=4)
    assert changes == []


def test_apply_delta_respects_max_active_cap() -> None:
    svc = _service(quest_max_active=1)
    existing = _quest()
    delta = QuestDelta(quests_new=[NewQuest(slug="another", title="Another", description="x")])
    changes = svc.apply_delta([existing], delta, turn_count=4)
    assert changes == []


def test_apply_delta_normalizes_unknown_quest_type() -> None:
    svc = _service()
    delta = QuestDelta(quests_new=[NewQuest(slug="q", title="Q", quest_type="fetch", description="x")])
    changes = svc.apply_delta([], delta, turn_count=1)
    assert changes[0].quest.quest_type == "promise"


# ---------------------------------------------------------------------------
# apply_delta — updates
# ---------------------------------------------------------------------------


def test_apply_delta_offered_becomes_active_with_accepted_turn() -> None:
    svc = _service()
    quest = _quest(status="offered", accepted_turn=None)
    delta = QuestDelta(quests_update=[QuestUpdateItem(slug=quest.slug, status="active")])
    changes = svc.apply_delta([quest], delta, turn_count=6)
    assert changes[0].change == "started"
    assert quest.status == "active"
    assert quest.accepted_turn == 6


def test_apply_delta_stage_completion_bumps_progress() -> None:
    svc = _service()
    quest = _quest(last_progress_turn=2)
    delta = QuestDelta(
        quests_update=[
            QuestUpdateItem(slug=quest.slug, stages_complete=["ask-around"], progress_note="Asked the innkeeper")
        ]
    )
    changes = svc.apply_delta([quest], delta, turn_count=8)
    assert changes[0].change == "advanced"
    assert quest.stages[0]["done"] is True
    assert quest.last_progress_turn == 8


def test_apply_delta_stage_done_never_reverts() -> None:
    svc = _service()
    quest = _quest(stages=[{"id": "ask-around", "description": "Ask", "done": True}])
    delta = QuestDelta(
        quests_update=[
            QuestUpdateItem(slug=quest.slug, stages_add=[QuestStage(id="ask-around", description="Ask", done=False)])
        ]
    )
    svc.apply_delta([quest], delta, turn_count=9)
    assert quest.stages[0]["done"] is True


def test_apply_delta_stages_capped() -> None:
    svc = _service(quest_max_stages=2)
    quest = _quest()
    delta = QuestDelta(
        quests_update=[
            QuestUpdateItem(
                slug=quest.slug,
                stages_add=[
                    QuestStage(id="s2", description="two"),
                    QuestStage(id="s3", description="three"),
                ],
            )
        ]
    )
    svc.apply_delta([quest], delta, turn_count=9)
    assert len(quest.stages) == 2


def test_apply_delta_completion_stores_resolution() -> None:
    svc = _service()
    quest = _quest()
    delta = QuestDelta(
        quests_update=[
            QuestUpdateItem(slug=quest.slug, status="completed", resolution="Sister found alive in Eastreach.")
        ]
    )
    changes = svc.apply_delta([quest], delta, turn_count=12)
    assert changes[0].change == "completed"
    assert quest.status == "completed"
    assert quest.resolved_turn == 12
    assert quest.resolution == "Sister found alive in Eastreach."


def test_apply_delta_terminal_quest_is_immutable() -> None:
    svc = _service()
    quest = _quest(status="completed", resolution="Done.")
    delta = QuestDelta(quests_update=[QuestUpdateItem(slug=quest.slug, status="active")])
    changes = svc.apply_delta([quest], delta, turn_count=14)
    assert changes == []
    assert quest.status == "completed"


def test_apply_delta_llm_cannot_set_escalating() -> None:
    svc = _service()
    quest = _quest()
    delta = QuestDelta(quests_update=[QuestUpdateItem(slug=quest.slug, status="escalating")])
    svc.apply_delta([quest], delta, turn_count=10)
    assert quest.status == "active"


def test_apply_delta_progress_unescalates() -> None:
    svc = _service()
    quest = _quest(status="escalating")
    delta = QuestDelta(
        quests_update=[QuestUpdateItem(slug=quest.slug, stages_complete=["ask-around"])]
    )
    svc.apply_delta([quest], delta, turn_count=20)
    assert quest.status == "active"
    assert quest.last_progress_turn == 20


# ---------------------------------------------------------------------------
# render_block / render_pressure
# ---------------------------------------------------------------------------


def test_render_block_empty_is_blank() -> None:
    assert QuestService.render_block([]) == ""


def test_render_block_shows_status_next_stage_and_stakes() -> None:
    quest = _quest()
    block = QuestService.render_block([quest])
    assert "ACTIVE QUESTS" in block
    assert "Find Maren's Sister" in block
    assert "next: Ask around the village" in block
    assert "stakes: Maren's sister is lost forever." in block


def test_render_block_marks_offers_as_not_taken_up() -> None:
    quest = _quest(status="offered")
    block = QuestService.render_block([quest])
    assert "offered, not yet taken up" in block


def test_render_pressure_empty_is_blank() -> None:
    assert QuestService.render_pressure([]) == ""


def test_render_pressure_lists_quests() -> None:
    pressure = QuestService.render_pressure([_quest()])
    assert "Find Maren's Sister" in pressure
    assert "Stakes:" in pressure


# ---------------------------------------------------------------------------
# extract_and_apply (DB)
# ---------------------------------------------------------------------------


async def test_extract_and_apply_persists_new_quest(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response(
        {
            "quests_new": [
                {
                    "slug": "find-marens-sister",
                    "title": "Find Maren's Sister",
                    "quest_type": "promise",
                    "description": "You promised Maren to find her sister.",
                    "stakes": "She is lost forever.",
                    "stages": [{"id": "ask-around", "description": "Ask around"}],
                }
            ]
        }
    )
    svc = QuestService(provider, make_test_settings(quests_enabled=True))
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    changes = await svc.extract_and_apply(
        db_session, session, user_message="I'll find your sister, Maren.", response_text="Maren weeps with relief."
    )
    assert len(changes) == 1
    rows = (await db_session.scalars(select(Quest).where(Quest.session_id == session.id))).all()
    assert len(rows) == 1
    assert rows[0].slug == "find-marens-sister"
    assert rows[0].status == "active"
    assert rows[0].origin == "emergent"


async def test_extract_and_apply_updates_existing_quest(db_session: AsyncSession) -> None:
    provider = MockProvider()
    svc = QuestService(provider, make_test_settings(quests_enabled=True))
    session = SessionFactory(turn_count=4)
    quest = QuestFactory(session=session, slug="find-marens-sister")
    await db_session.flush()

    provider.set_json_response(
        {
            "quests_update": [
                {"slug": "find-marens-sister", "stages_complete": ["ask-around"], "progress_note": "Innkeeper talked."}
            ]
        }
    )
    changes = await svc.extract_and_apply(db_session, session, user_message="a", response_text="b")
    assert changes[0].change == "advanced"
    await db_session.refresh(quest)
    assert quest.stages[0]["done"] is True
    assert quest.last_progress_turn == 4


async def test_extract_empty_delta_writes_nothing(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response({})
    svc = QuestService(provider, make_test_settings(quests_enabled=True))
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    changes = await svc.extract_and_apply(db_session, session, user_message="a", response_text="b")
    assert changes == []
    rows = (await db_session.scalars(select(Quest).where(Quest.session_id == session.id))).all()
    assert rows == []


async def test_extract_invalid_delta_is_noop(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response({"quests_new": "not a list"})
    svc = QuestService(provider, make_test_settings(quests_enabled=True))
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    changes = await svc.extract_and_apply(db_session, session, user_message="a", response_text="b")
    assert changes == []


async def test_extract_interval_gate_skips(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response({"quests_new": [{"slug": "q", "title": "Q", "description": "x"}]})
    svc = QuestService(provider, make_test_settings(quests_enabled=True, quest_extraction_interval=3))
    session = SessionFactory(turn_count=4)  # 4 % 3 != 0
    await db_session.flush()

    changes = await svc.extract_and_apply(db_session, session, user_message="a", response_text="b")
    assert changes == []


# ---------------------------------------------------------------------------
# offer_from_event (DB)
# ---------------------------------------------------------------------------


async def test_offer_from_event_creates_offered_quest(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response(
        {
            "slug": "the-masked-courier",
            "title": "The Masked Courier",
            "quest_type": "mystery",
            "description": "A courier slipped you a sealed letter.",
            "stakes": "The conspiracy goes unexposed.",
            "stages": [{"id": "read-letter", "description": "Read the letter"}],
        }
    )
    svc = QuestService(provider, make_test_settings(quests_enabled=True))
    session = SessionFactory(turn_count=6)
    await db_session.flush()

    quest = await svc.offer_from_event(
        db_session, session, event_seed="A mysterious courier", description="A masked figure presses a letter into your hand."
    )
    assert quest is not None
    assert quest.status == "offered"
    assert quest.origin == "gm_event"
    assert quest.created_turn == 6


async def test_offer_from_event_skips_duplicate_slug(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response(
        {"slug": "the-masked-courier", "title": "Dup", "description": "x", "stages": []}
    )
    svc = QuestService(provider, make_test_settings(quests_enabled=True))
    session = SessionFactory()
    QuestFactory(session=session, slug="the-masked-courier")
    await db_session.flush()

    quest = await svc.offer_from_event(db_session, session, event_seed="s", description="d")
    assert quest is None


async def test_offer_from_event_respects_cap(db_session: AsyncSession) -> None:
    provider = MockProvider()
    provider.set_json_response({"slug": "new-offer", "title": "New", "description": "x", "stages": []})
    svc = QuestService(provider, make_test_settings(quests_enabled=True, quest_max_active=1))
    session = SessionFactory()
    QuestFactory(session=session)
    await db_session.flush()

    quest = await svc.offer_from_event(db_session, session, event_seed="s", description="d")
    assert quest is None


# ---------------------------------------------------------------------------
# neglected / mark_escalating (DB)
# ---------------------------------------------------------------------------


async def test_neglected_returns_stale_active_quests(db_session: AsyncSession) -> None:
    svc = _service(quest_escalation_turns=10)
    session = SessionFactory(turn_count=20)
    stale = QuestFactory(session=session, status="active", last_progress_turn=5, last_escalation_turn=0)
    QuestFactory(session=session, status="active", last_progress_turn=18)  # fresh
    QuestFactory(session=session, status="offered", last_progress_turn=0)  # offers don't escalate
    await db_session.flush()

    neglected = await svc.neglected(db_session, session)
    assert [q.id for q in neglected] == [stale.id]


async def test_neglected_throttled_by_last_escalation(db_session: AsyncSession) -> None:
    svc = _service(quest_escalation_turns=10)
    session = SessionFactory(turn_count=20)
    QuestFactory(session=session, status="escalating", last_progress_turn=5, last_escalation_turn=15)
    await db_session.flush()

    neglected = await svc.neglected(db_session, session)
    assert neglected == []


async def test_mark_escalating_sets_status_and_turn(db_session: AsyncSession) -> None:
    svc = _service()
    session = SessionFactory(turn_count=20)
    quest = QuestFactory(session=session, status="active", last_progress_turn=5)
    await db_session.flush()

    changes = await svc.mark_escalating(db_session, session, [quest])
    assert len(changes) == 1
    assert changes[0].change == "escalated"
    assert quest.status == "escalating"
    assert quest.last_escalation_turn == 20
