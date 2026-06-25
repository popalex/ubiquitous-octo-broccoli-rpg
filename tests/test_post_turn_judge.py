"""Tests for the unified post-turn judge (§2).

Service-level: one combined call, per-section independence, flag gating.
Orchestrator-level: post-turn work runs through the judge (unconditionally).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Quest, WorldStateLedger
from app.services.items import ItemService
from app.services.orchestrator import OrchestratorService
from app.services.post_turn_judge import PostTurnJudgeService
from app.services.quests import QuestService
from app.services.world_state import WorldStateService
from tests.conftest import MockProvider, make_test_settings
from tests.factories import SessionFactory

WORLD_SECTION = {"entities_upsert": [{"id": "voss", "name": "Voss", "status": "dead"}]}
QUEST_SECTION = {
    "quests_new": [
        {
            "slug": "avenge-the-widow",
            "title": "Avenge the Widow",
            "quest_type": "promise",
            "description": "Find who burned the farm.",
            "stages": [{"id": "find-them", "description": "Find them"}],
        }
    ]
}
COMBINED = {"world_delta": WORLD_SECTION, "quest_delta": QUEST_SECTION}


class CountingMockProvider(MockProvider):
    """MockProvider that counts generate_json calls."""

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.json_calls = 0

    async def generate_json(self, messages, *, temperature, max_tokens) -> dict:
        self.json_calls += 1
        return await super().generate_json(messages, temperature=temperature, max_tokens=max_tokens)


def _judge(provider, settings) -> PostTurnJudgeService:
    return PostTurnJudgeService(
        provider,
        WorldStateService(provider, settings),
        QuestService(provider, settings),
        ItemService(settings),
        settings,
    )


async def _quest_count(db: AsyncSession, session_id: str) -> int:
    rows = (await db.scalars(select(Quest).where(Quest.session_id == session_id))).all()
    return len(rows)


# ---------------------------------------------------------------------------
# Service: one call, both sections applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_applies_both_sections_in_one_call(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=True, quests_enabled=True)
    provider = CountingMockProvider(settings)
    provider.set_json_response(COMBINED)
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="I cut down Voss and vow to avenge the widow", response_text="Voss falls."
    )

    assert provider.json_calls == 1  # the whole point of §2
    assert ledger_row is not None and ledger_row.version == 1
    assert len(changes) == 1
    assert await _quest_count(db_session, session.id) == 1


# ---------------------------------------------------------------------------
# Service: per-section independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_world_section_still_applies_quests(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=True, quests_enabled=True)
    provider = MockProvider(settings)
    provider.set_json_response({"world_delta": {"entities_upsert": "not a list"}, "quest_delta": QUEST_SECTION})
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert ledger_row is None  # malformed world section dropped
    assert len(changes) == 1  # quest section survived
    assert await WorldStateService(provider, settings).current_version(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_bad_quest_section_still_applies_world(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=True, quests_enabled=True)
    provider = MockProvider(settings)
    provider.set_json_response({"world_delta": WORLD_SECTION, "quest_delta": {"quests_new": "not a list"}})
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert ledger_row is not None and ledger_row.version == 1  # world section survived
    assert changes == []  # malformed quest section dropped
    assert await _quest_count(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_one_bad_quest_item_does_not_sink_the_valid_ones(db_session: AsyncSession) -> None:
    """A malformed quests_update item (missing slug) drops only itself; the
    valid quests_new in the same payload still applies (lenient parse)."""
    settings = make_test_settings(world_state_enabled=False, quests_enabled=True)
    provider = MockProvider(settings)
    quest_delta = {
        "quests_new": QUEST_SECTION["quests_new"],
        "quests_update": [{"status": "active"}],  # no slug -> invalid
    }
    provider.set_json_response({"quest_delta": quest_delta})
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    with patch("app.services.quests.quest_extract_failures") as failures:
        _ledger, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
            db_session, session, user_message="x", response_text="y"
        )

    assert len(changes) == 1  # valid new quest survived
    assert await _quest_count(db_session, session.id) == 1
    failures.add.assert_called_once_with(1, {"reason": "schema"})  # bad item metered


# ---------------------------------------------------------------------------
# Service: flag gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_world_only_session_skips_quests(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=True, quests_enabled=False)
    provider = CountingMockProvider(settings)
    # Model returns just the ledger fields at top level (world-only fallback).
    provider.set_json_response(WORLD_SECTION)
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert provider.json_calls == 1
    assert ledger_row is not None and ledger_row.version == 1
    assert changes == []
    assert await _quest_count(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_quests_only_session_skips_world(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=False, quests_enabled=True)
    provider = MockProvider(settings)
    provider.set_json_response(QUEST_SECTION)  # top-level quest fields (quests-only fallback)
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert ledger_row is None
    assert len(changes) == 1
    assert await WorldStateService(provider, settings).current_version(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_quest_interval_gate_skips_quest_section(db_session: AsyncSession) -> None:
    # Off-interval turns drop the quest section even though quests are enabled;
    # the world section still applies in the same call.
    settings = make_test_settings(world_state_enabled=True, quests_enabled=True, quest_extraction_interval=3)
    provider = CountingMockProvider(settings)
    provider.set_json_response(COMBINED)
    session = SessionFactory(turn_count=4)  # 4 % 3 != 0
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert provider.json_calls == 1
    assert ledger_row is not None and ledger_row.version == 1  # world still applied
    assert changes == []  # quest section gated out
    assert await _quest_count(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_no_call_when_both_features_off(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=False, quests_enabled=False)
    provider = CountingMockProvider(settings)
    session = SessionFactory(turn_count=2)
    await db_session.flush()

    ledger_row, changes, _suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert provider.json_calls == 0  # no enabled section -> no LLM call at all
    assert ledger_row is None and changes == []


# ---------------------------------------------------------------------------
# Service: suggestions section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_returned_and_one_call(db_session: AsyncSession) -> None:
    # World/quests off, suggestions on: the judge still fires exactly one call.
    settings = make_test_settings(world_state_enabled=False, quests_enabled=False)
    provider = CountingMockProvider(settings)
    provider.set_json_response({"suggestions": ["Search the desk", "Slip out the window"]})
    session = SessionFactory(turn_count=2, suggestions_enabled=True)
    await db_session.flush()

    ledger_row, changes, suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert provider.json_calls == 1
    assert ledger_row is None and changes == []
    assert suggestions == ["Search the desk", "Slip out the window"]


@pytest.mark.asyncio
async def test_suggestions_clamped_and_cleaned(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=False, quests_enabled=False, suggestions_max=2)
    provider = MockProvider(settings)
    # Blanks and non-strings dropped; clamped to suggestions_max (2).
    provider.set_json_response({"suggestions": ["  Fight  ", "", 7, "Flee", "Hide", None]})
    session = SessionFactory(turn_count=2, suggestions_enabled=True)
    await db_session.flush()

    _, _, suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert suggestions == ["Fight", "Flee"]


@pytest.mark.asyncio
async def test_suggestions_deduped_case_insensitively(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=False, quests_enabled=False)
    provider = MockProvider(settings)
    # A small model repeats a chip (varying case/whitespace); keep first only.
    provider.set_json_response({"suggestions": ["Search the desk", "search the desk ", "SEARCH THE DESK", "Flee"]})
    session = SessionFactory(turn_count=2, suggestions_enabled=True)
    await db_session.flush()

    _, _, suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert suggestions == ["Search the desk", "Flee"]


@pytest.mark.asyncio
async def test_malformed_suggestions_returns_empty(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=False, quests_enabled=False)
    provider = MockProvider(settings)
    provider.set_json_response({"suggestions": "not a list"})
    session = SessionFactory(turn_count=2, suggestions_enabled=True)
    await db_session.flush()

    _, _, suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert suggestions == []


@pytest.mark.asyncio
async def test_suggestions_off_session_yields_none(db_session: AsyncSession) -> None:
    # Suggestions disabled on the session: even if the model returns them, the
    # judge does not extract them (and with world/quests off, makes no call).
    settings = make_test_settings(world_state_enabled=False, quests_enabled=False)
    provider = CountingMockProvider(settings)
    provider.set_json_response({"suggestions": ["ignored"]})
    session = SessionFactory(turn_count=2, suggestions_enabled=False)
    await db_session.flush()

    _, _, suggestions, _items = await _judge(provider, settings).judge_turn(
        db_session, session, user_message="x", response_text="y"
    )

    assert provider.json_calls == 0
    assert suggestions == []


# ---------------------------------------------------------------------------
# Service: suggest_only (chronicle-reload regeneration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_only_returns_chips_without_touching_canon(db_session: AsyncSession) -> None:
    # Even with a quest payload present, suggest_only applies nothing — no
    # ledger row, no quests — and just returns cleaned suggestions.
    settings = make_test_settings(world_state_enabled=True, quests_enabled=True, suggestions_max=2)
    provider = CountingMockProvider(settings)
    provider.set_json_response({"quests_new": QUEST_SECTION["quests_new"], "suggestions": ["  Run  ", "", "Hide", "x"]})
    session = SessionFactory(turn_count=2, suggestions_enabled=True)
    await db_session.flush()

    suggestions = await _judge(provider, settings).suggest_only(session, user_message="x", response_text="y")

    assert provider.json_calls == 1
    assert suggestions == ["Run", "Hide"]
    assert await _quest_count(db_session, session.id) == 0
    assert await WorldStateService(provider, settings).current_version(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_suggest_only_off_session_makes_no_call(db_session: AsyncSession) -> None:
    settings = make_test_settings()
    provider = CountingMockProvider(settings)
    provider.set_json_response({"suggestions": ["ignored"]})
    session = SessionFactory(turn_count=2, suggestions_enabled=False)
    await db_session.flush()

    suggestions = await _judge(provider, settings).suggest_only(session, user_message="x", response_text="y")

    assert provider.json_calls == 0
    assert suggestions == []


# ---------------------------------------------------------------------------
# Orchestrator: post-turn work runs through the judge (now unconditional)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_routes_post_turn_through_judge(db_session: AsyncSession) -> None:
    settings = make_test_settings(world_state_enabled=True, quests_enabled=True)
    provider = MockProvider(settings)
    # The actor draft + continuity use generate_text/json with the default
    # payloads; script the post-turn judge's combined payload for generate_json.
    provider.set_json_responses([{"ok": True, "issues": [], "revised_response": "Voss falls."}, COMBINED])
    with patch("app.services.orchestrator.build_provider", return_value=provider):
        orch = OrchestratorService(settings)

    session = SessionFactory(turn_count=2)
    await db_session.flush()

    with patch.object(orch.post_turn_judge, "judge_turn", wraps=orch.post_turn_judge.judge_turn) as spy:
        await orch.chat(db_session, session.id, "I cut down Voss.")
    spy.assert_awaited_once()
    # World version was written through the judge path.
    rows = (await db_session.scalars(select(WorldStateLedger).where(WorldStateLedger.session_id == session.id))).all()
    assert len(rows) == 1
