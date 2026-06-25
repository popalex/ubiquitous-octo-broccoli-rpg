"""First-class items (todo-rpg Phase 4).

Structured per-chronicle inventory whose effects plug into the systems already
shipped: an equipped ``check_bonus`` item adds to the d20 skill check (Phase 1),
a ``heal`` consumable restores HP on use (Phase 3). The LLM proposes item gains/
losses via the post-turn judge; this service **validates the effect, clamps the
value, and applies it deterministically** (the "LLM proposes, engine applies"
foundation). Player Equip/Use actions go through the same service. Mirrors the
shape of ``QuestService`` / ``CharacterSheetService``; DB-touching methods are
best-effort and must never break a turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Item
from app.models import Session as ChatSession
from app.services.character_sheet import ATTRIBUTE_KEYS, CharacterSheetService, HpChangeResult
from app.telemetry import items_gained, items_used, tracer

logger = logging.getLogger(__name__)

# Effects an item can carry. ``check_bonus`` is a passive (equip) bonus to the
# d20 roll; ``heal`` is a consumable that restores HP on use. None = flavor.
EFFECT_TYPES: tuple[str, ...] = ("check_bonus", "heal")


class ItemGain(BaseModel):
    """One item the judge proposes the player gained."""

    name: str
    description: str | None = None
    qty: int = 1
    effect_type: str | None = None
    effect_value: int = 0
    effect_attribute: str | None = None


class ItemLoss(BaseModel):
    name: str
    qty: int = 1


class ItemDelta(BaseModel):
    """Item changes proposed by the post-turn judge for one exchange."""

    gained: list[ItemGain] = Field(default_factory=list)
    lost: list[ItemLoss] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.gained or self.lost)

    @classmethod
    def lenient(cls, raw: object) -> ItemDelta:
        """Parse a raw judge payload, dropping malformed items rather than
        failing the whole section (mirrors ``QuestDelta.lenient``)."""
        if not isinstance(raw, dict):
            return cls()
        gained: list[ItemGain] = []
        for item in raw.get("gained", []) or []:
            try:
                gained.append(ItemGain.model_validate(item))
            except Exception:
                continue
        lost: list[ItemLoss] = []
        for item in raw.get("lost", []) or []:
            try:
                lost.append(ItemLoss.model_validate(item))
            except Exception:
                continue
        return cls(gained=gained, lost=lost)


@dataclass
class ItemChange:
    """An applied item change, for chat beats / notifications."""

    name: str
    change: str  # gained | lost
    detail: str | None = None

    def notification(self) -> str:
        if self.change == "gained":
            return f"You acquired {self.name}{f' — {self.detail}' if self.detail else ''}."
        return f"You lost {self.name}."


class ItemService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.sheets = CharacterSheetService(settings)

    async def load_for_session(self, db: AsyncSession, session_id: str) -> list[Item]:
        return list(
            (await db.scalars(select(Item).where(Item.session_id == session_id).order_by(Item.created_at.asc()))).all()
        )

    # --- effect read paths ------------------------------------------------
    def check_bonus_for(self, items: list[Item], attribute: str | None) -> int:
        """Total d20 bonus from **equipped** ``check_bonus`` items that apply to
        ``attribute`` (an item with no ``effect_attribute`` applies to any check).
        Clamped to ``item_check_bonus_max`` so loot can't trivialise every roll."""
        attr = (attribute or "").strip().lower()
        total = 0
        for it in items:
            if not it.equipped or it.effect_type != "check_bonus":
                continue
            scope = (it.effect_attribute or "").strip().lower()
            if scope and scope != attr:
                continue
            total += it.effect_value
        return max(0, min(self.settings.item_check_bonus_max, total))

    # --- player actions ---------------------------------------------------
    async def equip(self, db: AsyncSession, session_id: str, item_id: str, equipped: bool) -> Item | None:
        """Equip/unequip an item. Returns the updated item, or None if not found
        / not equippable. Best-effort commit."""
        item = await db.scalar(select(Item).where(Item.id == item_id, Item.session_id == session_id))
        if item is None or item.consumable:
            return None
        item.equipped = equipped
        try:
            await db.commit()
        except SQLAlchemyError:
            logger.exception("item equip failed for session=%s item=%s", session_id, item_id)
            await db.rollback()
            return None
        return item

    async def use(
        self, db: AsyncSession, session: ChatSession, item_id: str, *, permadeath: bool
    ) -> tuple[HpChangeResult | None, list[str]]:
        """Consume one of a consumable item, applying its effect. For ``heal`` →
        restore HP via the sheet. Decrements qty (deletes at 0). Returns
        ``(hp_change_or_None, beats)``. Best-effort."""
        item = await db.scalar(select(Item).where(Item.id == item_id, Item.session_id == session.id))
        if item is None or not item.consumable or item.qty <= 0:
            return None, []
        beats: list[str] = []
        hp_change: HpChangeResult | None = None
        try:
            name = item.name
            if item.effect_type == "heal" and item.effect_value > 0:
                hp_change = await self.sheets.apply_heal(db, session.id, item.effect_value, reason="item")
            item.qty -= 1
            if item.qty <= 0:
                await db.delete(item)
            await db.commit()
            items_used.add(1)
            beats.append(f"You used {name}.")
            if hp_change is not None:
                beats.extend(hp_change.notifications())
        except SQLAlchemyError:
            logger.exception("item use failed for session=%s item=%s", session.id, item_id)
            await db.rollback()
            return None, []
        return hp_change, beats

    # --- judge-proposed deltas (LLM proposes, engine applies) -------------
    def _normalize_gain(self, gain: ItemGain) -> Item | None:
        """Build a validated Item from a proposed gain (None if effect invalid)."""
        effect_type = (gain.effect_type or "").strip().lower() or None
        if effect_type is not None and effect_type not in EFFECT_TYPES:
            effect_type = None  # unknown effect → keep as flavor rather than reject
        value = max(0, gain.effect_value)
        attribute = None
        consumable = False
        if effect_type == "check_bonus":
            value = min(self.settings.item_check_bonus_max, value)
            scope = (gain.effect_attribute or "").strip().lower()
            attribute = scope if scope in ATTRIBUTE_KEYS else None
        elif effect_type == "heal":
            consumable = True
        return Item(
            name=gain.name.strip()[:120],
            description=(gain.description or None),
            qty=max(1, gain.qty),
            equipped=False,
            consumable=consumable,
            effect_type=effect_type,
            effect_value=value,
            effect_attribute=attribute,
        )

    async def apply_item_delta(self, db: AsyncSession, session: ChatSession, delta: ItemDelta) -> list[ItemChange]:
        """Apply judge-proposed gains/losses. Validates + clamps effects, enforces
        ``item_max``, and stacks gains onto a same-named item. Commits its own
        write; best-effort — never raises into the turn."""
        if delta.is_empty():
            return []
        with tracer.start_as_current_span("orchestrator.item_delta") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            try:
                existing = await self.load_for_session(db, session.id)
                by_name = {it.name.casefold(): it for it in existing}
                changes: list[ItemChange] = []

                for gain in delta.gained:
                    if not gain.name.strip():
                        continue
                    key = gain.name.strip().casefold()
                    match = by_name.get(key)
                    if match is not None:
                        match.qty += max(1, gain.qty)  # stack
                        changes.append(ItemChange(name=match.name, change="gained"))
                        continue
                    if len(existing) >= self.settings.item_max:
                        continue  # cap reached
                    new_item = self._normalize_gain(gain)
                    if new_item is None:
                        continue
                    new_item.session_id = session.id
                    db.add(new_item)
                    existing.append(new_item)
                    by_name[key] = new_item
                    detail = self._effect_label(new_item)
                    changes.append(ItemChange(name=new_item.name, change="gained", detail=detail))

                for loss in delta.lost:
                    match = by_name.get(loss.name.strip().casefold())
                    if match is None:
                        continue
                    match.qty -= max(1, loss.qty)
                    if match.qty <= 0:
                        await db.delete(match)
                    changes.append(ItemChange(name=match.name, change="lost"))

                await db.commit()
                if any(c.change == "gained" for c in changes):
                    items_gained.add(sum(1 for c in changes if c.change == "gained"), {"source": "judge"})
                return changes
            except Exception:
                logger.exception("item delta apply failed for session=%s", session.id)
                await db.rollback()
                return []

    @staticmethod
    def _effect_label(item: Item) -> str | None:
        """Short human label for an item's effect, used in the gain beat."""
        if item.effect_type == "check_bonus":
            scope = f" {item.effect_attribute.upper()}" if item.effect_attribute else ""
            return f"+{item.effect_value}{scope} on checks"
        if item.effect_type == "heal":
            return f"restores {item.effect_value} HP"
        return None
