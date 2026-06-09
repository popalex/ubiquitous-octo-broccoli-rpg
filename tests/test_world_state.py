from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldStateLedger
from app.services.world_state import (
    InventoryChange,
    Ledger,
    LedgerDelta,
    LedgerEntity,
    LedgerInventoryItem,
    LedgerLocation,
    LedgerThread,
    WorldStateService,
)
from tests.conftest import MockProvider, make_test_settings
from tests.factories import SessionFactory


def _service(**setting_overrides) -> WorldStateService:
    settings = make_test_settings(world_state_enabled=True, **setting_overrides)
    return WorldStateService(MockProvider(settings), settings)


# ---------------------------------------------------------------------------
# Delta application — entities
# ---------------------------------------------------------------------------


def test_apply_delta_adds_entity() -> None:
    svc = _service()
    ledger = Ledger()
    delta = LedgerDelta(entities_upsert=[LedgerEntity(id="kael", name="Kael", status="alive")])
    result = svc.apply_delta(ledger, delta)
    assert len(result.entities) == 1
    assert result.entities[0].name == "Kael"


def test_apply_delta_updates_entity_and_merges_facts() -> None:
    svc = _service()
    ledger = Ledger(entities=[LedgerEntity(id="kael", name="Kael", facts=["swore an oath"])])
    delta = LedgerDelta(
        entities_upsert=[
            LedgerEntity(id="kael", name="Kael", relationship_to_player="ally", facts=["swore an oath", "wounded"])
        ]
    )
    result = svc.apply_delta(ledger, delta)
    assert len(result.entities) == 1
    kael = result.entities[0]
    assert kael.relationship_to_player == "ally"
    # No duplicate fact, new fact appended.
    assert kael.facts == ["swore an oath", "wounded"]


def test_apply_delta_removes_entity() -> None:
    svc = _service()
    ledger = Ledger(entities=[LedgerEntity(id="kael", name="Kael", status="alive")])
    delta = LedgerDelta(entities_remove=["kael"])
    result = svc.apply_delta(ledger, delta)
    assert result.entities == []


def test_dead_stays_dead_on_update() -> None:
    svc = _service()
    ledger = Ledger(entities=[LedgerEntity(id="kael", name="Kael", status="dead")])
    delta = LedgerDelta(entities_upsert=[LedgerEntity(id="kael", name="Kael", status="alive")])
    result = svc.apply_delta(ledger, delta)
    assert result.entities[0].status == "dead"


def test_dead_stays_dead_on_remove() -> None:
    svc = _service()
    ledger = Ledger(entities=[LedgerEntity(id="kael", name="Kael", status="dead")])
    delta = LedgerDelta(entities_remove=["kael"])
    result = svc.apply_delta(ledger, delta)
    # A death is permanent canon — removal must not erase it.
    assert len(result.entities) == 1
    assert result.entities[0].status == "dead"


# ---------------------------------------------------------------------------
# Delta application — inventory math
# ---------------------------------------------------------------------------


def test_inventory_qty_delta_subtracts() -> None:
    svc = _service()
    ledger = Ledger(inventory=[LedgerInventoryItem(item="gold", qty=20)])
    delta = LedgerDelta(inventory_changes=[InventoryChange(item="gold", qty_delta=-12)])
    result = svc.apply_delta(ledger, delta)
    assert result.inventory[0].qty == 8


def test_inventory_qty_delta_to_zero_removes_item() -> None:
    svc = _service()
    ledger = Ledger(inventory=[LedgerInventoryItem(item="gold", qty=10)])
    delta = LedgerDelta(inventory_changes=[InventoryChange(item="gold", qty_delta=-10)])
    result = svc.apply_delta(ledger, delta)
    assert result.inventory == []


def test_inventory_set_qty_and_add_new() -> None:
    svc = _service()
    ledger = Ledger(inventory=[LedgerInventoryItem(item="gold", qty=5)])
    delta = LedgerDelta(
        inventory_changes=[
            InventoryChange(item="gold", set_qty=3),
            InventoryChange(item="rusted key", set_qty=1),
        ]
    )
    result = svc.apply_delta(ledger, delta)
    by_item = {i.item: i.qty for i in result.inventory}
    assert by_item == {"gold": 3, "rusted key": 1}


def test_inventory_explicit_remove() -> None:
    svc = _service()
    ledger = Ledger(inventory=[LedgerInventoryItem(item="torch", qty=1)])
    delta = LedgerDelta(inventory_changes=[InventoryChange(item="torch", remove=True)])
    result = svc.apply_delta(ledger, delta)
    assert result.inventory == []


# ---------------------------------------------------------------------------
# Delta application — threads & facts
# ---------------------------------------------------------------------------


def test_thread_resolution() -> None:
    svc = _service()
    ledger = Ledger(threads=[LedgerThread(id="find-heir", summary="Find the heir", status="open")])
    delta = LedgerDelta(threads_upsert=[LedgerThread(id="find-heir", summary="Find the heir", status="resolved")])
    result = svc.apply_delta(ledger, delta)
    assert result.threads[0].status == "resolved"


def test_facts_add_dedups_existing() -> None:
    svc = _service()
    ledger = Ledger(facts=["The bridge is destroyed."])
    delta = LedgerDelta(facts_add=["The bridge is destroyed.", "The well is poisoned."])
    result = svc.apply_delta(ledger, delta)
    assert result.facts == ["The bridge is destroyed.", "The well is poisoned."]


def test_facts_remove() -> None:
    svc = _service()
    ledger = Ledger(facts=["The bridge is destroyed.", "The well is poisoned."])
    delta = LedgerDelta(facts_remove=["The bridge is destroyed."])
    result = svc.apply_delta(ledger, delta)
    assert result.facts == ["The well is poisoned."]


# ---------------------------------------------------------------------------
# Pruning / caps
# ---------------------------------------------------------------------------


def test_prune_caps_facts_keeping_recent() -> None:
    svc = _service(world_state_max_facts=3)
    ledger = Ledger(facts=[f"fact {i}" for i in range(5)])
    delta = LedgerDelta(facts_add=["fact 5"])
    result = svc.apply_delta(ledger, delta)
    assert result.facts == ["fact 3", "fact 4", "fact 5"]


def test_prune_caps_threads_dropping_resolved_first() -> None:
    svc = _service(world_state_max_threads=2)
    ledger = Ledger(
        threads=[
            LedgerThread(id="t1", summary="resolved one", status="resolved"),
            LedgerThread(id="t2", summary="open one", status="open"),
            LedgerThread(id="t3", summary="open two", status="open"),
        ]
    )
    result = svc.apply_delta(ledger, LedgerDelta())
    ids = {t.id for t in result.threads}
    # Both open threads survive; the resolved one is dropped.
    assert ids == {"t2", "t3"}


def test_prune_caps_entities_protecting_dead() -> None:
    svc = _service(world_state_max_entities=2)
    ledger = Ledger(
        entities=[
            LedgerEntity(id="dead1", name="Ghost", status="dead"),
            LedgerEntity(id="a1", name="Alive1", status="alive"),
            LedgerEntity(id="a2", name="Alive2", status="alive"),
        ]
    )
    result = svc.apply_delta(ledger, LedgerDelta())
    ids = {e.id for e in result.entities}
    assert "dead1" in ids
    assert len(result.entities) == 2


# ---------------------------------------------------------------------------
# render_block
# ---------------------------------------------------------------------------


def test_render_block_empty_is_blank() -> None:
    assert WorldStateService.render_block(Ledger()) == ""


def test_render_block_leads_with_dead() -> None:
    ledger = Ledger(
        location=LedgerLocation(name="Eastreach"),
        entities=[
            LedgerEntity(id="kael", name="Kael", status="dead"),
            LedgerEntity(id="mira", name="Mira", status="alive", relationship_to_player="ally"),
        ],
        inventory=[LedgerInventoryItem(item="gold", qty=8)],
        threads=[LedgerThread(id="t1", summary="Find the heir", status="open")],
        facts=["The bridge is destroyed."],
    )
    block = WorldStateService.render_block(ledger)
    assert "CANONICAL WORLD STATE" in block
    assert "Dead (must stay dead): Kael" in block
    assert "Mira" in block
    assert "gold x8" in block
    assert "Find the heir" in block
    assert "The bridge is destroyed." in block


# ---------------------------------------------------------------------------
# extract_and_apply (DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_and_apply_persists_version(db_session: Session) -> None:
    provider = MockProvider()
    provider.set_json_response(
        {
            "entities_upsert": [{"id": "kael", "name": "Kael", "status": "dead"}],
            "facts_add": ["Kael fell to the wraith."],
        }
    )
    settings = make_test_settings(world_state_enabled=True)
    svc = WorldStateService(provider, settings)
    session = SessionFactory(turn_count=2)
    db_session.flush()

    row = await svc.extract_and_apply(
        db_session, session, user_message="I strike the wraith", gm_response="Kael falls, slain."
    )
    assert row is not None
    assert row.version == 1

    ledger = svc.load_current(db_session, session.id)
    assert ledger.entities[0].status == "dead"
    assert "Kael fell to the wraith." in ledger.facts


@pytest.mark.asyncio
async def test_extract_increments_version(db_session: Session) -> None:
    provider = MockProvider()
    provider.set_json_response({"facts_add": ["fact one"]})
    svc = WorldStateService(provider, make_test_settings(world_state_enabled=True))
    session = SessionFactory(turn_count=2)
    db_session.flush()

    await svc.extract_and_apply(db_session, session, user_message="a", gm_response="b")
    provider.set_json_response({"facts_add": ["fact two"]})
    row = await svc.extract_and_apply(db_session, session, user_message="c", gm_response="d")
    assert row.version == 2

    rows = db_session.scalars(
        select(WorldStateLedger).where(WorldStateLedger.session_id == session.id)
    ).all()
    assert len(rows) == 2
    ledger = svc.load_current(db_session, session.id)
    assert ledger.facts == ["fact one", "fact two"]


@pytest.mark.asyncio
async def test_extract_empty_delta_writes_nothing(db_session: Session) -> None:
    provider = MockProvider()
    provider.set_json_response({})
    svc = WorldStateService(provider, make_test_settings(world_state_enabled=True))
    session = SessionFactory(turn_count=2)
    db_session.flush()

    row = await svc.extract_and_apply(db_session, session, user_message="a", gm_response="b")
    assert row is None
    assert svc.current_version(db_session, session.id) == 0


@pytest.mark.asyncio
async def test_extract_invalid_provider_json_skips(db_session: Session) -> None:
    # MockProvider.generate_json returns a non-dict-shaped payload that fails
    # schema validation -> extraction is skipped, turn is never broken.
    provider = MockProvider()
    provider.set_json_response({"entities_upsert": "not a list"})
    svc = WorldStateService(provider, make_test_settings(world_state_enabled=True))
    session = SessionFactory(turn_count=2)
    db_session.flush()

    row = await svc.extract_and_apply(db_session, session, user_message="a", gm_response="b")
    assert row is None
    assert svc.current_version(db_session, session.id) == 0


def test_load_current_empty_when_no_rows(db_session: Session) -> None:
    svc = WorldStateService(MockProvider(), make_test_settings(world_state_enabled=True))
    session = SessionFactory()
    db_session.flush()
    ledger = svc.load_current(db_session, session.id)
    assert ledger.is_empty()
