"""First-class items (todo-rpg Phase 4): effect reads, judge-applied deltas,
equip/use, the dice-modifier bonus, routes, and fork inheritance."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item
from app.services.fork import ForkService
from app.services.items import ItemDelta, ItemGain, ItemLoss, ItemService
from app.services.orchestrator import OrchestratorService
from app.services.post_turn_judge import PostTurnJudgeService
from app.services.quests import QuestService
from app.services.world_state import WorldStateService
from tests.conftest import MockProvider, make_test_settings
from tests.factories import CharacterSheetFactory, ItemFactory, SessionFactory

# ---------------------------------------------------------------------------
# check_bonus_for (pure)
# ---------------------------------------------------------------------------


def test_check_bonus_for_sums_equipped_matching() -> None:
    svc = ItemService(make_test_settings(item_check_bonus_max=5))
    items = [
        ItemFactory.build(equipped=True, effect_type="check_bonus", effect_value=2, effect_attribute="finesse"),
        ItemFactory.build(equipped=True, effect_type="check_bonus", effect_value=1, effect_attribute=None),  # any
        ItemFactory.build(equipped=True, effect_type="check_bonus", effect_value=3, effect_attribute="might"),  # other
        ItemFactory.build(equipped=False, effect_type="check_bonus", effect_value=2, effect_attribute="finesse"),  # off
        ItemFactory.build(equipped=True, effect_type="heal", effect_value=5),  # not a check bonus
    ]
    # finesse: 2 (finesse) + 1 (any) = 3; the might item and unequipped/heal don't count.
    assert svc.check_bonus_for(items, "finesse") == 3
    # might: 3 (might) + 1 (any) = 4.
    assert svc.check_bonus_for(items, "might") == 4


def test_check_bonus_for_clamps() -> None:
    svc = ItemService(make_test_settings(item_check_bonus_max=3))
    items = [ItemFactory.build(equipped=True, effect_type="check_bonus", effect_value=10, effect_attribute=None)]
    assert svc.check_bonus_for(items, "wits") == 3


# ---------------------------------------------------------------------------
# apply_item_delta (judge → engine)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_item_delta_creates_validated_items(db_session: AsyncSession) -> None:
    svc = ItemService(make_test_settings(item_check_bonus_max=5))
    session = SessionFactory()
    await db_session.flush()

    delta = ItemDelta(
        gained=[
            ItemGain(name="Fine Lockpick", effect_type="check_bonus", effect_value=9, effect_attribute="finesse"),
            ItemGain(name="Healing Draught", qty=2, effect_type="heal", effect_value=6),
            ItemGain(name="Sealed Letter"),  # flavor
            ItemGain(name="Cursed Idol", effect_type="bogus", effect_value=99),  # unknown effect → flavor
        ]
    )
    changes = await svc.apply_item_delta(db_session, session, delta)
    assert {c.name for c in changes} == {"Fine Lockpick", "Healing Draught", "Sealed Letter", "Cursed Idol"}

    by_name = {it.name: it for it in await svc.load_for_session(db_session, session.id)}
    assert by_name["Fine Lockpick"].effect_value == 5  # clamped from 9
    assert by_name["Fine Lockpick"].effect_attribute == "finesse"
    assert by_name["Fine Lockpick"].consumable is False
    assert by_name["Healing Draught"].consumable is True and by_name["Healing Draught"].qty == 2
    assert by_name["Sealed Letter"].effect_type is None
    assert by_name["Cursed Idol"].effect_type is None  # unknown effect dropped to flavor


@pytest.mark.asyncio
async def test_apply_item_delta_stacks_and_loses(db_session: AsyncSession) -> None:
    svc = ItemService(make_test_settings())
    session = SessionFactory()
    ItemFactory(session=session, name="Torch", qty=2)
    await db_session.flush()

    await svc.apply_item_delta(db_session, session, ItemDelta(gained=[ItemGain(name="Torch", qty=3)]))
    await svc.apply_item_delta(db_session, session, ItemDelta(lost=[ItemLoss(name="Torch", qty=1)]))
    items = await svc.load_for_session(db_session, session.id)
    assert len(items) == 1 and items[0].qty == 4  # 2 + 3 - 1

    # Losing the rest removes the row.
    await svc.apply_item_delta(db_session, session, ItemDelta(lost=[ItemLoss(name="Torch", qty=99)]))
    assert await svc.load_for_session(db_session, session.id) == []


def test_item_delta_lenient_drops_bad_entries() -> None:
    delta = ItemDelta.lenient({"gained": [{"name": "Rope"}, {"no_name": True}], "lost": "nonsense"})
    assert [g.name for g in delta.gained] == ["Rope"]
    assert delta.lost == []


# ---------------------------------------------------------------------------
# equip / use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_equip_toggles(db_session: AsyncSession) -> None:
    svc = ItemService(make_test_settings())
    item = ItemFactory(effect_type="check_bonus", effect_value=1, equipped=False)
    await db_session.flush()

    updated = await svc.equip(db_session, item.session_id, item.id, True)
    assert updated is not None and updated.equipped is True


@pytest.mark.asyncio
async def test_use_heal_consumes_and_restores_hp(db_session: AsyncSession) -> None:
    svc = ItemService(make_test_settings())
    session = SessionFactory()
    CharacterSheetFactory(session=session, hp=5, max_hp=20)
    item = ItemFactory(session=session, name="Draught", consumable=True, effect_type="heal", effect_value=8, qty=2)
    await db_session.flush()

    hp_change, beats = await svc.use(db_session, session, item.id, permadeath=False)
    assert hp_change is not None and hp_change.hp == 13  # 5 + 8
    assert any("Draught" in b for b in beats)
    # One consumed, one left.
    remaining = await svc.load_for_session(db_session, session.id)
    assert len(remaining) == 1 and remaining[0].qty == 1


# ---------------------------------------------------------------------------
# Orchestrator: equipped item adds to the d20 modifier
# ---------------------------------------------------------------------------

_SHEET_ASSESSMENT = {
    "requires_check": True,
    "skill_label": "Sleight of Hand",
    "attribute": "finesse",
    "dc": 12,
    "stakes": "none",
    "rationale": "a delicate lock",
}


def _orch(mock_provider: MockProvider, **overrides) -> OrchestratorService:
    settings = make_test_settings(
        memory_summary_interval=100,
        event_check_interval=100,
        dice_enabled=True,
        character_sheet_enabled=True,
        items_enabled=True,
        world_state_enabled=False,
        quests_enabled=False,
        suggestions_enabled=False,
        **overrides,
    )
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        return OrchestratorService(settings)


@pytest.mark.asyncio
async def test_equipped_item_boosts_the_roll(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    orchestrator = _orch(mock_provider)
    mock_provider.set_json_responses([_SHEET_ASSESSMENT, {"ok": True, "issues": [], "revised_response": ""}])
    session = SessionFactory(gm_enabled=True, turn_count=1)
    CharacterSheetFactory(session=session, finesse=1)
    ItemFactory(
        session=session,
        name="Fine Lockpick",
        equipped=True,
        effect_type="check_bonus",
        effect_value=2,
        effect_attribute="finesse",
    )
    await db_session.flush()

    result = await orchestrator.gm_chat(db_session, session.id, "I pick the lock.")
    assert result.roll is not None
    # attribute_mod (finesse 1) + equipped item bonus (2) = 3.
    assert result.roll.modifier == 3
    assert result.roll.total == result.roll.die + 3


# ---------------------------------------------------------------------------
# Post-turn judge item extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_extracts_items(mock_provider: MockProvider, db_session: AsyncSession) -> None:
    settings = make_test_settings()  # world/quests/suggestions off → items-only section
    judge = PostTurnJudgeService(
        mock_provider,
        WorldStateService(mock_provider, settings),
        QuestService(mock_provider, settings),
        ItemService(settings),
        settings,
    )
    session = SessionFactory(items_enabled=True)
    await db_session.flush()
    mock_provider.set_json_response(
        {"item_delta": {"gained": [{"name": "Brass Key", "effect_type": "check_bonus", "effect_value": 1}]}}
    )

    _, _, _, item_changes = await judge.judge_turn(
        db_session, session, user_message="I pocket the brass key.", response_text="It's yours."
    )
    assert [c.name for c in item_changes] == ["Brass Key"]
    rows = await ItemService(settings).load_for_session(db_session, session.id)
    assert len(rows) == 1 and rows[0].name == "Brass Key"


# ---------------------------------------------------------------------------
# Routes + fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_routes(async_client: AsyncClient, db_session: AsyncSession) -> None:
    session = SessionFactory()
    gear = ItemFactory(session=session, name="Lockpick", effect_type="check_bonus", effect_value=1)
    ItemFactory(session=session, name="Potion", consumable=True, effect_type="heal", effect_value=5)
    CharacterSheetFactory(session=session, hp=2, max_hp=20)
    await db_session.flush()

    listing = await async_client.get(f"/session/{session.id}/items")
    assert listing.status_code == 200 and len(listing.json()["items"]) == 2

    equipped = await async_client.post(f"/session/{session.id}/items/{gear.id}/equip", json={"equipped": True})
    assert equipped.status_code == 200 and equipped.json()["equipped"] is True


@pytest.mark.asyncio
async def test_fork_copies_items(db_session: AsyncSession) -> None:
    parent = SessionFactory(turn_count=0)
    ItemFactory(session=parent, name="Heirloom Blade", equipped=True, effect_type="check_bonus", effect_value=2)
    await db_session.flush()

    fork = await ForkService.fork_session(db_session, parent, at_turn=0)
    fork_items = (await db_session.scalars(select(Item).where(Item.session_id == fork.id))).all()
    assert len(fork_items) == 1 and fork_items[0].name == "Heirloom Blade" and fork_items[0].equipped is True
