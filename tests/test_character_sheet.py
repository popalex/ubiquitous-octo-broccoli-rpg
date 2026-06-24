"""Character sheet & progression (todo-rpg Phases 1+2): curve + XP/leveling math,
attribute modifiers, seeding on chronicle creation, fork inheritance, and the
orchestrator skill-check integration (modifier applied, XP granted, level-up
surfaced)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CharacterSheet, DiceRoll
from app.services.character_sheet import CharacterSheetService
from app.services.dice import FAILURE, SUCCESS
from app.services.fork import ForkService
from app.services.orchestrator import OrchestratorService
from app.services.quests import QuestChange
from tests.conftest import MockProvider, make_test_settings
from tests.factories import CharacterCardFactory, CharacterSheetFactory, QuestFactory, SessionFactory, TurnFactory

# ---------------------------------------------------------------------------
# Curve (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("xp", "level", "to_next"),
    [(0, 1, 100), (40, 1, 60), (99, 1, 1), (100, 2, 100), (250, 3, 50)],
)
def test_curve(xp: int, level: int, to_next: int) -> None:
    svc = CharacterSheetService(make_test_settings(sheet_xp_curve_base=100))
    assert svc.level_for_xp(xp) == level
    assert svc.xp_to_next(xp) == to_next
    assert svc.xp_for_level() == 100


# ---------------------------------------------------------------------------
# attribute_mod
# ---------------------------------------------------------------------------


def test_attribute_mod() -> None:
    svc = CharacterSheetService(make_test_settings())
    sheet = CharacterSheetFactory.build(might=3, finesse=2)
    assert svc.attribute_mod(sheet, "might") == 3
    assert svc.attribute_mod(sheet, "FINESSE") == 2  # case-insensitive
    assert svc.attribute_mod(sheet, "luck") == 0  # unknown key
    assert svc.attribute_mod(sheet, None) == 0
    assert svc.attribute_mod(None, "might") == 0  # no sheet


# ---------------------------------------------------------------------------
# grant_xp + leveling (needs a db row — commits its own write)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_xp_single_level_bumps_triggering_attribute(db_session: AsyncSession) -> None:
    svc = CharacterSheetService(make_test_settings(sheet_xp_curve_base=100))
    sheet = CharacterSheetFactory(might=1, finesse=1, wits=1, presence=1, level=1, xp=0)
    await db_session.flush()

    result = await svc.grant_xp(db_session, sheet.session_id, 100, attribute_key="finesse", reason="check")

    assert result is not None
    assert (result.old_level, result.new_level) == (1, 2)
    assert sheet.level == 2
    assert sheet.finesse == 2  # the exercised attribute grew
    assert result.bumps == [("finesse", 2)]


@pytest.mark.asyncio
async def test_grant_xp_multi_level_jump(db_session: AsyncSession) -> None:
    svc = CharacterSheetService(make_test_settings(sheet_xp_curve_base=100))
    sheet = CharacterSheetFactory(might=1, level=1, xp=0)
    await db_session.flush()

    result = await svc.grant_xp(db_session, sheet.session_id, 250, attribute_key="might")

    assert result is not None and result.new_level == 3  # 250 XP -> level 3
    assert sheet.might == 3  # two bumps from level 1->3


@pytest.mark.asyncio
async def test_grant_xp_falls_back_to_lowest_attribute(db_session: AsyncSession) -> None:
    # No governing attribute (e.g. quest-completion XP): bump the lowest to round
    # the character out.
    svc = CharacterSheetService(make_test_settings(sheet_xp_curve_base=100))
    sheet = CharacterSheetFactory(might=1, finesse=2, wits=3, presence=4, level=1, xp=0)
    await db_session.flush()

    result = await svc.grant_xp(db_session, sheet.session_id, 100)

    assert result is not None and result.bumps == [("might", 2)]


@pytest.mark.asyncio
async def test_grant_xp_clamps_at_max(db_session: AsyncSession) -> None:
    svc = CharacterSheetService(make_test_settings(sheet_xp_curve_base=100, sheet_attribute_max=6))
    sheet = CharacterSheetFactory(might=6, finesse=6, wits=6, presence=6, level=1, xp=0)
    await db_session.flush()

    result = await svc.grant_xp(db_session, sheet.session_id, 100, attribute_key="might")

    assert result is not None and result.new_level == 2
    assert result.bumps == []  # everything capped, level still rises
    assert sheet.might == 6


@pytest.mark.asyncio
async def test_grant_xp_no_level_returns_none(db_session: AsyncSession) -> None:
    svc = CharacterSheetService(make_test_settings(sheet_xp_curve_base=100))
    sheet = CharacterSheetFactory(level=1, xp=0)
    await db_session.flush()

    assert await svc.grant_xp(db_session, sheet.session_id, 40) is None  # below the threshold
    assert sheet.xp == 40
    assert await svc.grant_xp(db_session, sheet.session_id, 0) is None  # no-op


# ---------------------------------------------------------------------------
# Seeding on /session/init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_seeds_sheet_when_enabled(async_client: AsyncClient, db_session: AsyncSession) -> None:
    character = CharacterCardFactory()
    await db_session.flush()

    response = await async_client.post(
        "/session/init",
        json={"character_card_id": character.id, "character_sheet_enabled": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["character_sheet_enabled"] is True
    assert data["sheet"] is not None
    assert data["sheet"]["level"] == 1
    # all four attributes seeded at the starting value
    assert {data["sheet"][k] for k in ("might", "finesse", "wits", "presence")} == {1}

    rows = (
        await db_session.scalars(select(CharacterSheet).where(CharacterSheet.session_id == data["session_id"]))
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_init_no_sheet_when_disabled(async_client: AsyncClient, db_session: AsyncSession) -> None:
    character = CharacterCardFactory()
    await db_session.flush()

    response = await async_client.post(
        "/session/init",
        json={"character_card_id": character.id, "character_sheet_enabled": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["character_sheet_enabled"] is False
    assert data["sheet"] is None
    rows = (
        await db_session.scalars(select(CharacterSheet).where(CharacterSheet.session_id == data["session_id"]))
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_get_sheet_route(async_client: AsyncClient, db_session: AsyncSession) -> None:
    sheet = CharacterSheetFactory(might=2, level=1, xp=30)
    await db_session.flush()

    response = await async_client.get(f"/session/{sheet.session_id}/sheet")
    assert response.status_code == 200
    body = response.json()
    assert body["might"] == 2
    assert body["xp"] == 30
    assert body["xp_to_next"] == 70  # default curve base 100

    # 404 for a session without a sheet
    other = SessionFactory()
    await db_session.flush()
    missing = await async_client.get(f"/session/{other.id}/sheet")
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Fork inheritance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_copies_sheet(db_session: AsyncSession) -> None:
    parent = SessionFactory(turn_count=0)
    CharacterSheetFactory(session=parent, might=4, finesse=2, wits=3, presence=5, level=3, xp=220)
    await db_session.flush()

    fork = await ForkService.fork_session(db_session, parent, at_turn=0)

    fork_sheet = await db_session.scalar(select(CharacterSheet).where(CharacterSheet.session_id == fork.id))
    assert fork_sheet is not None
    assert (fork_sheet.might, fork_sheet.finesse, fork_sheet.wits, fork_sheet.presence) == (4, 2, 3, 5)
    assert (fork_sheet.level, fork_sheet.xp) == (3, 220)


# ---------------------------------------------------------------------------
# Orchestrator skill-check integration
# ---------------------------------------------------------------------------

_SHEET_ASSESSMENT = {
    "requires_check": True,
    "skill_label": "Stealth",
    "attribute": "finesse",
    "dc": 10,
    "rationale": "shadowed alley -> moderate",
}


def _sheet_orchestrator(mock_provider: MockProvider, **overrides) -> OrchestratorService:
    settings = make_test_settings(
        memory_summary_interval=100,
        event_check_interval=100,
        dice_enabled=True,
        character_sheet_enabled=True,
        world_state_enabled=False,
        quests_enabled=False,
        suggestions_enabled=False,
        **overrides,
    )
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        return OrchestratorService(settings)


@pytest.mark.asyncio
async def test_skill_check_applies_sheet_modifier(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    orchestrator = _sheet_orchestrator(mock_provider)
    mock_provider.set_json_responses([_SHEET_ASSESSMENT, {"ok": True, "issues": [], "revised_response": ""}])
    session = SessionFactory(gm_enabled=True, turn_count=1)
    CharacterSheetFactory(session=session, finesse=3)
    await db_session.flush()

    result = await orchestrator.gm_chat(db_session, session.id, "I sneak past the guard.")

    assert result.roll is not None
    assert result.roll.attribute == "finesse"
    assert result.roll.modifier == 3
    assert result.roll.total == result.roll.die + 3

    row = await db_session.scalar(select(DiceRoll).where(DiceRoll.session_id == session.id))
    assert row is not None and row.modifier == 3 and row.attribute == "finesse"


@pytest.mark.asyncio
async def test_successful_check_grants_xp_and_levels_up(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    # Force a SUCCESS and size the reward to cross a level so the advancement beat
    # and attribute bump are deterministic.
    orchestrator = _sheet_orchestrator(mock_provider, sheet_xp_curve_base=100, xp_per_success=100)
    mock_provider.set_json_responses([_SHEET_ASSESSMENT, {"ok": True, "issues": [], "revised_response": ""}])
    session = SessionFactory(gm_enabled=True, turn_count=1)
    sheet = CharacterSheetFactory(session=session, finesse=3, level=1, xp=0)
    await db_session.flush()

    with patch("app.services.orchestrator.roll_check", return_value=(15, 18, SUCCESS)):
        result = await orchestrator.gm_chat(db_session, session.id, "I sneak past the guard.")

    assert result.advancement  # "You reached level 2." + "FINESSE increased to +4."
    assert any("level 2" in line for line in result.advancement)
    await db_session.refresh(sheet)
    assert sheet.level == 2
    assert sheet.xp == 100
    assert sheet.finesse == 4  # the exercised attribute grew


@pytest.mark.asyncio
async def test_failed_check_grants_no_xp(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    orchestrator = _sheet_orchestrator(mock_provider, xp_per_success=100)
    mock_provider.set_json_responses([_SHEET_ASSESSMENT, {"ok": True, "issues": [], "revised_response": ""}])
    session = SessionFactory(gm_enabled=True, turn_count=1)
    sheet = CharacterSheetFactory(session=session, finesse=3, level=1, xp=0)
    await db_session.flush()

    with patch("app.services.orchestrator.roll_check", return_value=(2, 5, FAILURE)):
        result = await orchestrator.gm_chat(db_session, session.id, "I sneak past the guard.")

    assert result.advancement == []
    await db_session.refresh(sheet)
    assert sheet.xp == 0 and sheet.level == 1


async def _collect(stream) -> list[dict]:
    return [json.loads(c.removeprefix("data: ").strip()) async for c in stream]


@pytest.mark.asyncio
async def test_gm_stream_emits_advancement_frame(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    # The frontend only consumes the streamed path, so the level-up beat must
    # arrive as an `advancement` SSE frame (not just the non-stream response).
    orchestrator = _sheet_orchestrator(mock_provider, sheet_xp_curve_base=100, xp_per_success=100)
    mock_provider.set_json_response(_SHEET_ASSESSMENT)
    session = SessionFactory(gm_enabled=True, turn_count=1)
    CharacterSheetFactory(session=session, finesse=3, level=1, xp=0)
    await db_session.flush()

    with patch("app.services.orchestrator.roll_check", return_value=(15, 18, SUCCESS)):
        events = await _collect(orchestrator.gm_chat_stream(db_session, session.id, "I sneak past the guard."))

    adv = [e for e in events if e.get("type") == "advancement"]
    assert len(adv) == 1
    assert any("level 2" in line for line in adv[0]["advancement"])


@pytest.mark.asyncio
async def test_quest_completion_grants_xp(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    # A completed quest awards a flat reward via _apply_progression, with no
    # governing attribute -> the lowest attribute is bumped on the level-up.
    orchestrator = _sheet_orchestrator(mock_provider, sheet_xp_curve_base=100, xp_per_quest_complete=100)
    session = SessionFactory(gm_enabled=True, turn_count=1)
    sheet = CharacterSheetFactory(session=session, might=1, finesse=2, wits=3, presence=4, level=1, xp=0)
    assistant_turn = TurnFactory(session=session, turn_index=2, role="assistant", content="The deed is done.")
    await db_session.flush()

    # _apply_progression only reads `.change`; a transient quest avoids attaching
    # to the persisted session (which triggers a cascade SAWarning).
    completed = QuestChange(quest=QuestFactory.build(), change="completed")
    advancement = await orchestrator._apply_progression(db_session, session, None, [completed], assistant_turn)

    assert any("level 2" in line for line in advancement)
    await db_session.refresh(sheet)
    assert sheet.xp == 100
    assert sheet.might == 2  # lowest attribute bumped (no check attribute to credit)
    # Persisted on the turn so a chronicle reload re-renders the beat.
    assert assistant_turn.advancement_json == advancement


@pytest.mark.asyncio
async def test_turns_route_attaches_persisted_advancement(async_client: AsyncClient, db_session: AsyncSession) -> None:
    """Regression: GET /session/{id}/turns must re-attach persisted level-up beats
    so a chronicle reload re-renders them (mirrors the dice-roll re-attach)."""
    session = SessionFactory()
    await db_session.flush()
    TurnFactory(session=session, turn_index=1, role="user", content="I force the lock.")
    TurnFactory(
        session=session,
        turn_index=2,
        role="assistant",
        content="The lock yields.",
        advancement_json=["You reached level 2.", "FINESSE increased to +4."],
    )
    await db_session.flush()

    response = await async_client.get(f"/session/{session.id}/turns")
    assert response.status_code == 200
    by_index = {t["turn_index"]: t for t in response.json()}
    assert by_index[1]["advancement"] is None
    assert by_index[2]["advancement"] == ["You reached level 2.", "FINESSE increased to +4."]
