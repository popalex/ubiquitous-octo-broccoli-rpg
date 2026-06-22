"""Dice / skill checks (§4c): pure roll logic, GM assessment, feature
resolution, and orchestrator integration (GM stream + non-stream)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DiceRoll
from app.providers.base import ProviderError
from app.schemas import GMChatResponse
from app.services.dice import (
    CRITICAL_SUCCESS,
    FAILURE,
    SUCCESS,
    clamp_dc,
    message_may_need_check,
    roll_check,
    roll_directive,
)
from app.services.features import dice_on
from app.services.game_master import GameMasterService
from app.services.orchestrator import OrchestratorService
from tests.conftest import MockProvider, make_test_settings
from tests.factories import SessionFactory


class _FixedRng:
    """A stand-in for ``random.Random`` whose ``randint`` always returns ``v``."""

    def __init__(self, v: int) -> None:
        self.v = v

    def randint(self, a: int, b: int) -> int:
        return self.v


# ---------------------------------------------------------------------------
# roll_check — pure outcome classification (no critical-failure tier)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("die", "dc", "expected"),
    [
        (20, 10, CRITICAL_SUCCESS),  # nat 20 always crits
        (20, 20, CRITICAL_SUCCESS),  # crit beats the "die >= dc" branch
        (15, 10, SUCCESS),
        (10, 10, SUCCESS),  # meets DC = success
        (9, 10, FAILURE),
        (1, 2, FAILURE),  # nat 1 is just a failure — no fumble tier
    ],
)
def test_roll_check_outcomes(die: int, dc: int, expected: str) -> None:
    rolled, outcome = roll_check(dc, rng=_FixedRng(die))
    assert rolled == die
    assert outcome == expected


def test_roll_check_never_returns_critical_failure() -> None:
    # Sweep every die value against a mid DC — only the three defined tiers appear.
    outcomes = {roll_check(10, rng=_FixedRng(d))[1] for d in range(1, 21)}
    assert outcomes <= {CRITICAL_SUCCESS, SUCCESS, FAILURE}


@pytest.mark.parametrize(("raw", "expected"), [(0, 2), (1, 2), (12, 12), (20, 20), (99, 20)])
def test_clamp_dc(raw: int, expected: int) -> None:
    assert clamp_dc(raw) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("", False),
        ("   ", False),
        ("What do the blue lanterns mean tonight?", False),  # pure question -> skip
        ("Who are you?", False),
        ("I try to slip past the harbor guards.", True),  # action statement
        ("I attack the goblin!", True),
        ("I sneak in. Is the vault open?", True),  # has a "." -> not a bare question
        ("I climb the wall", True),
    ],
)
def test_message_may_need_check(message: str, expected: bool) -> None:
    assert message_may_need_check(message) is expected


def test_roll_directive_mentions_skill_dc_and_verdict() -> None:
    text = roll_directive("Stealth", 12, 7, FAILURE)
    assert "Stealth" in text
    assert "12" in text
    assert "7" in text
    assert "FAILURE" in text


# ---------------------------------------------------------------------------
# GameMasterService.assess_action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assess_action_no_check(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    mock_provider.set_json_response({"requires_check": False})
    gm = GameMasterService(mock_provider, make_test_settings())
    session = SessionFactory()
    await db_session.flush()

    assessment = await gm.assess_action(db_session, session, "I look around the room.")
    assert assessment.requires_check is False


@pytest.mark.asyncio
async def test_assess_action_clamps_dc(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    mock_provider.set_json_response(
        {"requires_check": True, "skill_label": "Athletics", "dc": 99, "rationale": "frail scholar -> very hard"}
    )
    gm = GameMasterService(mock_provider, make_test_settings())
    session = SessionFactory()
    await db_session.flush()

    assessment = await gm.assess_action(db_session, session, "I leap the chasm.")
    assert assessment.requires_check is True
    assert assessment.skill_label == "Athletics"
    assert assessment.dc == 20  # clamped from 99
    assert "frail scholar" in assessment.rationale


@pytest.mark.asyncio
async def test_assess_action_provider_failure_is_no_check(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    # Best-effort: a provider error must yield "no check", never break the turn.
    mock_provider.generate_json = AsyncMock(side_effect=ProviderError("boom"))
    gm = GameMasterService(mock_provider, make_test_settings())
    session = SessionFactory()
    await db_session.flush()

    assessment = await gm.assess_action(db_session, session, "I leap the chasm.")
    assert assessment.requires_check is False


# ---------------------------------------------------------------------------
# Feature resolution (session override → global)
# ---------------------------------------------------------------------------


def test_dice_on_resolution() -> None:
    on = make_test_settings(dice_enabled=True)
    off = make_test_settings(dice_enabled=False)
    session = SessionFactory.build()

    session.dice_enabled = None  # inherit global
    assert dice_on(session, on) is True
    assert dice_on(session, off) is False

    session.dice_enabled = True  # override wins
    assert dice_on(session, off) is True
    session.dice_enabled = False
    assert dice_on(session, on) is False


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

# event_check_interval=100 + turn_count=1 makes check_for_event early-exit with
# no LLM call (1 % 100 != 0); world/quests/suggestions off so the post-turn judge
# makes no call either — the assessment is then the only generate_json in flight.
_ASSESSMENT = {"requires_check": True, "skill_label": "Stealth", "dc": 12, "rationale": "nimble rogue -> easy"}


def _dice_orchestrator(mock_provider: MockProvider, *, dice_enabled: bool = True) -> OrchestratorService:
    settings = make_test_settings(
        memory_summary_interval=100,
        event_check_interval=100,
        dice_enabled=dice_enabled,
        world_state_enabled=False,
        quests_enabled=False,
        suggestions_enabled=False,
    )
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        return OrchestratorService(settings)


async def _collect(stream) -> list[dict]:
    return [json.loads(c.removeprefix("data: ").strip()) async for c in stream]


@pytest.mark.asyncio
async def test_gm_stream_emits_roll_and_persists(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    orchestrator = _dice_orchestrator(mock_provider)
    mock_provider.set_json_response(_ASSESSMENT)
    session = SessionFactory(gm_enabled=True, turn_count=1)
    await db_session.flush()

    events = await _collect(orchestrator.gm_chat_stream(db_session, session.id, "I sneak past the guard."))

    rolls = [e for e in events if e.get("type") == "roll"]
    assert len(rolls) == 1
    roll = rolls[0]["roll"]
    assert roll["skill_label"] == "Stealth"
    assert roll["dc"] == 12
    assert 1 <= roll["die"] <= 20
    assert roll["outcome"] in {CRITICAL_SUCCESS, SUCCESS, FAILURE}

    rows = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == session.id))).all()
    assert len(rows) == 1
    assert rows[0].dc == 12
    assert rows[0].skill_label == "Stealth"
    assert rows[0].turn_id is not None


@pytest.mark.asyncio
async def test_gm_stream_no_roll_when_dice_off(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    orchestrator = _dice_orchestrator(mock_provider, dice_enabled=False)
    mock_provider.set_json_response(_ASSESSMENT)
    session = SessionFactory(gm_enabled=True, turn_count=1)
    await db_session.flush()

    events = await _collect(orchestrator.gm_chat_stream(db_session, session.id, "I sneak past the guard."))

    assert not any(e.get("type") == "roll" for e in events)
    rows = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == session.id))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_gm_stream_no_roll_when_action_needs_no_check(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    # Dice ON, but the GM judges the action as not needing a check — the common
    # case, distinct from dice being disabled.
    orchestrator = _dice_orchestrator(mock_provider)
    mock_provider.set_json_response({"requires_check": False})
    session = SessionFactory(gm_enabled=True, turn_count=1)
    await db_session.flush()

    events = await _collect(orchestrator.gm_chat_stream(db_session, session.id, "I glance at the sky."))

    assert not any(e.get("type") == "roll" for e in events)
    rows = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == session.id))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_gm_stream_skips_assessment_for_question(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    # Even with dice ON and an assessment queued, a pure question is gated out
    # before the assess_action call — so no roll despite _ASSESSMENT being set.
    orchestrator = _dice_orchestrator(mock_provider)
    mock_provider.set_json_response(_ASSESSMENT)
    session = SessionFactory(gm_enabled=True, turn_count=1)
    await db_session.flush()

    events = await _collect(orchestrator.gm_chat_stream(db_session, session.id, "What do the lanterns mean?"))

    assert not any(e.get("type") == "roll" for e in events)
    rows = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == session.id))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_standard_chat_never_rolls(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    # Skill checks are GM-mode only: the standard chat path must never roll even
    # with dice globally enabled.
    orchestrator = _dice_orchestrator(mock_provider)
    mock_provider.set_json_response(_ASSESSMENT)
    session = SessionFactory(turn_count=1)
    await db_session.flush()

    await orchestrator.chat(db_session, session.id, "I sneak past the guard.")

    rows = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == session.id))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_persist_dice_roll_commits(mock_provider: MockProvider) -> None:
    # Regression: the row must be COMMITTED, not just flushed. get_db never
    # commits on its own, and the turns were already committed upstream, so a
    # bare flush here is discarded when the request session closes. (The
    # savepoint-based db_session fixture can't tell flush from commit apart, so
    # this guards it directly.)
    from app.schemas import DiceRollResult

    orchestrator = _dice_orchestrator(mock_provider)
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    roll = DiceRollResult(skill_label="Stealth", dc=12, die=7, outcome="failure", rationale=None)

    await orchestrator._persist_dice_roll(db, SessionFactory.build(), roll, "01ABCDEF01ABCDEF01ABCDEF01")

    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_gm_chat_returns_roll(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    orchestrator = _dice_orchestrator(mock_provider)
    # gm_chat (non-stream) runs continuity too; FIFO: assessment, then a passing
    # continuity payload.
    mock_provider.set_json_responses([_ASSESSMENT, {"ok": True, "issues": [], "revised_response": ""}])
    session = SessionFactory(gm_enabled=True, turn_count=1)
    await db_session.flush()

    result = await orchestrator.gm_chat(db_session, session.id, "I pick the lock.")
    assert isinstance(result, GMChatResponse)
    assert result.roll is not None
    assert result.roll.skill_label == "Stealth"
    assert result.roll.dc == 12

    rows = (await db_session.scalars(select(DiceRoll).where(DiceRoll.session_id == session.id))).all()
    assert len(rows) == 1
