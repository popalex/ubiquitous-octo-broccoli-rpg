"""World-state ledger service.

Maintains an authoritative, structured record of canon per session — what is
*true* (entities, inventory, open threads, location, misc facts) — that is
injected into the GM/actor prompt as hard constraints and updated every turn.

Complements pgvector retrieval: retrieval answers "what's relevant right now?"
(fuzzy), the ledger answers "what must not be contradicted?" (structured).

The ledger is versioned: each turn that changes canon writes a new immutable
snapshot row. The latest version is current canon.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Session as ChatSession
from app.models import WorldStateLedger
from app.prompts import WORLD_STATE_EXTRACT_PROMPT
from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
from app.telemetry import canon_extract_failures, canon_size, record_span_error, set_completion, tracer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ledger schema (the structured canon snapshot)
# ---------------------------------------------------------------------------


class LedgerLocation(BaseModel):
    name: str | None = None
    description: str | None = None


class LedgerEntity(BaseModel):
    id: str
    name: str
    kind: str = "npc"  # npc | player | item | faction
    status: str | None = None  # alive | dead | ...
    facts: list[str] = Field(default_factory=list)
    relationship_to_player: str | None = None


class LedgerInventoryItem(BaseModel):
    item: str
    qty: int | None = None


class LedgerThread(BaseModel):
    id: str
    summary: str
    status: str = "open"  # open | resolved


class Ledger(BaseModel):
    location: LedgerLocation | None = None
    entities: list[LedgerEntity] = Field(default_factory=list)
    inventory: list[LedgerInventoryItem] = Field(default_factory=list)
    threads: list[LedgerThread] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)

    @property
    def size(self) -> int:
        """Rough canon size used for telemetry and budgeting."""
        return len(self.entities) + len(self.threads) + len(self.facts)

    def is_empty(self) -> bool:
        return not (self.entities or self.inventory or self.threads or self.facts or self.location)


# ---------------------------------------------------------------------------
# Delta schema (what changed this turn)
# ---------------------------------------------------------------------------


class InventoryChange(BaseModel):
    item: str
    qty_delta: int | None = None  # relative change (e.g. spent gold: -12)
    set_qty: int | None = None  # absolute quantity
    remove: bool = False


class LedgerDelta(BaseModel):
    location: LedgerLocation | None = None
    entities_upsert: list[LedgerEntity] = Field(default_factory=list)
    entities_remove: list[str] = Field(default_factory=list)
    inventory_changes: list[InventoryChange] = Field(default_factory=list)
    threads_upsert: list[LedgerThread] = Field(default_factory=list)
    facts_add: list[str] = Field(default_factory=list)
    facts_remove: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.location
            or self.entities_upsert
            or self.entities_remove
            or self.inventory_changes
            or self.threads_upsert
            or self.facts_add
            or self.facts_remove
        )

    def summary_counts(self) -> dict[str, int]:
        return {
            "entities_upsert": len(self.entities_upsert),
            "entities_remove": len(self.entities_remove),
            "inventory_changes": len(self.inventory_changes),
            "threads_upsert": len(self.threads_upsert),
            "facts_add": len(self.facts_add),
            "facts_remove": len(self.facts_remove),
        }


class WorldStateService:
    def __init__(
        self,
        extract_provider: BaseModelProvider,
        settings: Settings | None = None,
    ) -> None:
        self.extract_provider = extract_provider
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def load_current(self, db: AsyncSession, session_id: str) -> Ledger:
        """Return the latest ledger snapshot for a session (empty if none)."""
        row = await db.scalar(
            select(WorldStateLedger)
            .where(WorldStateLedger.session_id == session_id)
            .order_by(WorldStateLedger.version.desc())
            .limit(1)
        )
        if row is None:
            return Ledger()
        try:
            return Ledger.model_validate(row.state)
        except ValidationError:
            logger.exception("corrupt world-state row id=%s; treating as empty", row.id)
            return Ledger()

    async def current_version(self, db: AsyncSession, session_id: str) -> int:
        row = await db.scalar(
            select(WorldStateLedger.version)
            .where(WorldStateLedger.session_id == session_id)
            .order_by(WorldStateLedger.version.desc())
            .limit(1)
        )
        return int(row) if row is not None else 0

    # ------------------------------------------------------------------
    # Inject
    # ------------------------------------------------------------------

    @staticmethod
    def render_block(ledger: Ledger) -> str:
        """Render the ledger as an authoritative, imperative prompt block.

        Highest-stakes invariants (deaths, location) lead. Returns "" when the
        ledger is empty so callers can skip injection.
        """
        if ledger.is_empty():
            return ""

        lines: list[str] = [
            "CANONICAL WORLD STATE — these facts are TRUE. Do not contradict them:",
        ]

        if ledger.location and (ledger.location.name or ledger.location.description):
            loc = ledger.location.name or ""
            if ledger.location.description:
                loc = f"{loc} — {ledger.location.description}".strip(" —")
            lines.append(f"Location: {loc}")

        # Lead with the dead — the most common continuity break.
        dead = [e for e in ledger.entities if (e.status or "").lower() == "dead"]
        if dead:
            lines.append("Dead (must stay dead): " + ", ".join(e.name for e in dead))

        living = [e for e in ledger.entities if (e.status or "").lower() != "dead"]
        if living:
            lines.append("Entities:")
            for e in living:
                bits = [e.name]
                meta = ", ".join(
                    part
                    for part in (
                        e.kind if e.kind and e.kind != "npc" else "",
                        f"status: {e.status}" if e.status else "",
                        f"toward player: {e.relationship_to_player}" if e.relationship_to_player else "",
                    )
                    if part
                )
                if meta:
                    bits.append(f"({meta})")
                if e.facts:
                    bits.append("— " + "; ".join(e.facts))
                lines.append("  - " + " ".join(bits))

        if ledger.inventory:
            inv = ", ".join(
                f"{item.item} x{item.qty}" if item.qty is not None else item.item for item in ledger.inventory
            )
            lines.append(f"Inventory: {inv}")

        open_threads = [t for t in ledger.threads if (t.status or "").lower() != "resolved"]
        if open_threads:
            lines.append("Open threads:")
            for t in open_threads:
                lines.append(f"  - {t.summary}")

        if ledger.facts:
            lines.append("Facts:")
            for fact in ledger.facts:
                lines.append(f"  - {fact}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Delta application
    # ------------------------------------------------------------------

    def apply_delta(self, ledger: Ledger, delta: LedgerDelta) -> Ledger:
        """Apply a delta to a ledger, returning a new pruned Ledger.

        Invariants enforced here (not trusted to the model):
        - the dead stay dead (an upsert can never revive a dead entity);
        - inventory quantities never go negative; items at qty<=0 are dropped.
        """
        # Work on a deep copy so the input is never mutated.
        new = ledger.model_copy(deep=True)

        if delta.location is not None:
            new.location = delta.location

        # Entities — upsert by id, merge facts, protect the dead.
        by_id = {e.id: e for e in new.entities}
        for upsert in delta.entities_upsert:
            existing = by_id.get(upsert.id)
            if existing is None:
                by_id[upsert.id] = upsert.model_copy(deep=True)
                new.entities.append(by_id[upsert.id])
                continue
            existing.name = upsert.name or existing.name
            existing.kind = upsert.kind or existing.kind
            # Dead stays dead: never let an update revive a corpse.
            if (existing.status or "").lower() != "dead":
                existing.status = upsert.status or existing.status
            if upsert.relationship_to_player:
                existing.relationship_to_player = upsert.relationship_to_player
            for fact in upsert.facts:
                if fact not in existing.facts:
                    existing.facts.append(fact)

        if delta.entities_remove:
            remove = set(delta.entities_remove)
            # Never drop a dead entity — deaths are permanent canon.
            new.entities = [e for e in new.entities if e.id not in remove or (e.status or "").lower() == "dead"]

        # Inventory math.
        inv_by_item = {item.item: item for item in new.inventory}
        for change in delta.inventory_changes:
            current = inv_by_item.get(change.item)
            # Treat malformed/no-op changes as no-ops (avoid creating qty=0 items).
            if not change.remove and change.set_qty is None and change.qty_delta is None:
                continue
            if change.remove:
                if current is not None:
                    new.inventory.remove(current)
                    del inv_by_item[change.item]
                continue
            if change.set_qty is not None:
                qty = change.set_qty
            else:
                base = current.qty if current and current.qty is not None else 0
                qty = base + (change.qty_delta or 0)
            if qty <= 0 and (change.set_qty is not None or change.qty_delta is not None):
                if current is not None:
                    new.inventory.remove(current)
                    del inv_by_item[change.item]
                continue
                if current is not None:
                    new.inventory.remove(current)
                    del inv_by_item[change.item]
                continue
            if current is None:
                current = LedgerInventoryItem(item=change.item, qty=qty)
                new.inventory.append(current)
                inv_by_item[change.item] = current
            else:
                current.qty = qty

        # Threads — upsert by id.
        thread_by_id = {t.id: t for t in new.threads}
        for thread in delta.threads_upsert:
            existing_thread = thread_by_id.get(thread.id)
            if existing_thread is None:
                thread_by_id[thread.id] = thread.model_copy(deep=True)
                new.threads.append(thread_by_id[thread.id])
            else:
                existing_thread.summary = thread.summary or existing_thread.summary
                existing_thread.status = thread.status or existing_thread.status

        # Facts.
        if delta.facts_remove:
            remove_facts = set(delta.facts_remove)
            new.facts = [f for f in new.facts if f not in remove_facts]
        for fact in delta.facts_add:
            if fact not in new.facts:
                new.facts.append(fact)

        return self._prune(new)

    def _prune(self, ledger: Ledger) -> Ledger:
        """Cap unbounded collections so the ledger always fits the prompt.

        Drops resolved threads first, then oldest; keeps the most recent facts;
        caps entities (preserving the dead, which are permanent canon).
        """
        max_threads = self.settings.world_state_max_threads
        if len(ledger.threads) > max_threads:
            open_threads = [t for t in ledger.threads if (t.status or "").lower() != "resolved"]
            resolved = [t for t in ledger.threads if (t.status or "").lower() == "resolved"]
            # Keep all open; backfill with most-recent resolved up to the cap.
            kept = open_threads[-max_threads:]
            remaining = max_threads - len(kept)
            if remaining > 0:
                kept = resolved[-remaining:] + kept
            ledger.threads = kept

        max_facts = self.settings.world_state_max_facts
        if len(ledger.facts) > max_facts:
            ledger.facts = ledger.facts[-max_facts:]

        max_entities = self.settings.world_state_max_entities
        if len(ledger.entities) > max_entities:
            dead = [e for e in ledger.entities if (e.status or "").lower() == "dead"]
            alive = [e for e in ledger.entities if (e.status or "").lower() != "dead"]
            if len(dead) >= max_entities:
                # Cap exceeded by the dead alone — keep the most recent dead.
                ledger.entities = dead[-max_entities:]
            else:
                # Preserve all dead (permanent canon); backfill with recent alive.
                room = max_entities - len(dead)
                ledger.entities = dead + alive[-room:]

        return ledger

    # ------------------------------------------------------------------
    # Extract (after the turn)
    # ------------------------------------------------------------------

    async def extract_and_apply(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        gm_response: str,
        turn_id: str | None = None,
    ) -> WorldStateLedger | None:
        """Extract a delta from the latest exchange, apply it, and persist a new
        version. Returns the new row, or ``None`` if nothing changed or the
        extraction failed (failures are logged + metered, never raised)."""
        with tracer.start_as_current_span("orchestrator.state_extract") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            ledger = await self.load_current(db, session.id)
            base_version = await self.current_version(db, session.id)
            span.set_attribute("rpg.canon.version", base_version)

            user_content = (
                f"CURRENT LEDGER:\n{ledger.model_dump_json()}\n\n"
                f"LATEST EXCHANGE:\nPLAYER: {user_message}\nRESPONSE: {gm_response}"
            )
            try:
                payload = await self.extract_provider.generate_json(
                    [
                        ProviderMessage(role="system", content=WORLD_STATE_EXTRACT_PROMPT),
                        ProviderMessage(role="user", content=user_content),
                    ],
                    temperature=0.1,
                    max_tokens=self.settings.world_state_extract_max_tokens,
                )
            except ProviderError as exc:
                logger.exception("world-state extract failed for session=%s", session.id)
                canon_extract_failures.add(1, {"reason": "provider"})
                record_span_error(span, exc)
                return None

            try:
                delta = LedgerDelta.model_validate(payload)
            except ValidationError as exc:
                logger.warning("world-state delta invalid for session=%s: %s", session.id, exc)
                canon_extract_failures.add(1, {"reason": "schema"})
                record_span_error(span, exc)
                return None

            for key, value in delta.summary_counts().items():
                span.set_attribute(f"rpg.canon.delta.{key}", value)

            if delta.is_empty():
                span.set_attribute("rpg.canon.delta.empty", True)
                return None

            from sqlalchemy.exc import IntegrityError

            new_ledger = self.apply_delta(ledger, delta)
            try:
                row = WorldStateLedger(
                    session_id=session.id,
                    version=base_version + 1,
                    turn_id=turn_id,
                    state=new_ledger.model_dump(),
                )
                db.add(row)
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                logger.warning("world-state version conflict for session=%s; skipping", session.id)
                canon_extract_failures.add(1, {"reason": "conflict"})
                record_span_error(span, exc)
                return None

            span.set_attribute("rpg.canon.version", base_version + 1)
            span.set_attribute("rpg.canon.size", new_ledger.size)
            set_completion(span, delta.model_dump_json())
            canon_size.record(new_ledger.size)
            logger.info(
                "state_extract session=%s version=%s size=%s delta=%s",
                session.id,
                base_version + 1,
                new_ledger.size,
                delta.summary_counts(),
            )
            return row
