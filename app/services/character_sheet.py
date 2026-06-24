"""Character sheet & progression (todo-rpg Phases 1+2).

The engine-side authority for a chronicle's :class:`CharacterSheet`: it seeds the
sheet at chronicle creation, exposes the attribute modifier the d20 check adds,
and applies XP / leveling **deterministically** (the LLM only ever proposes which
attribute a check used and how much XP a beat is worth — never the math). Mirrors
the shape of ``WorldStateService`` / ``QuestService``: constructed with
``Settings``, all DB-touching methods are best-effort and must never break a turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import CharacterSheet
from app.models import Session as ChatSession
from app.telemetry import attribute_bumps, hp_damage, hp_healed, level_ups, sheet_downs, tracer, xp_granted

logger = logging.getLogger(__name__)

# The four light-system attributes (flat d20 modifiers). The skill check's
# governing attribute is one of these keys; unknown/missing keys yield 0.
ATTRIBUTE_KEYS: tuple[str, ...] = ("might", "finesse", "wits", "presence")

# HP stakes a failed check can carry, in ascending severity. "none" → no damage.
STAKES_KEYS: tuple[str, ...] = ("none", "minor", "major")


@dataclass
class LevelUpResult:
    """Outcome of a level-crossing :meth:`CharacterSheetService.grant_xp` call."""

    old_level: int
    new_level: int
    # (attribute_key, new_value) for each attribute bumped while leveling.
    bumps: list[tuple[str, int]] = field(default_factory=list)

    def notifications(self) -> list[str]:
        """Player-facing 'you improved X' beats surfaced in chat."""
        msgs = [f"You reached level {self.new_level}."]
        for attr, value in self.bumps:
            msgs.append(f"{attr.upper()} increased to +{value}.")
        return msgs


@dataclass
class HpChangeResult:
    """Outcome of an HP change (damage or heal). ``downed`` is set the moment HP
    hits 0; ``died`` only when the chronicle has permadeath on."""

    amount: int  # signed: negative for damage, positive for heal
    hp: int
    max_hp: int
    downed: bool = False
    died: bool = False

    def notifications(self) -> list[str]:
        """Player-facing HP beats surfaced in chat."""
        if self.died:
            return [f"You have fallen. ({self.hp}/{self.max_hp} HP) — this chronicle ends."]
        if self.downed:
            return [f"You are downed! ({self.hp}/{self.max_hp} HP) — you need to recover."]
        if self.amount < 0:
            return [f"You take {-self.amount} damage. ({self.hp}/{self.max_hp} HP)"]
        if self.amount > 0:
            return [f"You recover {self.amount} HP. ({self.hp}/{self.max_hp} HP)"]
        return []


class CharacterSheetService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # --- curve (pure, unit-testable) -------------------------------------
    def level_for_xp(self, xp: int) -> int:
        """Level implied by cumulative ``xp``. Flat curve: each level costs
        ``sheet_xp_curve_base`` XP (level 1 at 0 XP)."""
        base = max(1, self.settings.sheet_xp_curve_base)
        return max(1, xp // base + 1)

    def xp_to_next(self, xp: int) -> int:
        """XP remaining until the next level from cumulative ``xp``."""
        base = max(1, self.settings.sheet_xp_curve_base)
        return base - (xp % base)

    def xp_for_level(self) -> int:
        """Total XP spanning one level (the denominator for an XP progress bar).
        Flat curve, so it's constant; a method keeps callers curve-agnostic."""
        return max(1, self.settings.sheet_xp_curve_base)

    # --- attributes ------------------------------------------------------
    def attribute_mod(self, sheet: CharacterSheet | None, attribute_key: str | None) -> int:
        """Flat d20 modifier for ``attribute_key``. No sheet / unknown key → 0."""
        if sheet is None or not attribute_key:
            return 0
        key = attribute_key.strip().lower()
        if key not in ATTRIBUTE_KEYS:
            return 0
        return int(getattr(sheet, key))

    # --- persistence -----------------------------------------------------
    async def load_for_session(self, db: AsyncSession, session_id: str) -> CharacterSheet | None:
        return await db.scalar(select(CharacterSheet).where(CharacterSheet.session_id == session_id))

    async def ensure_for_session(self, db: AsyncSession, session: ChatSession) -> CharacterSheet:
        """Return the session's sheet, creating it with seeded defaults if absent.

        Caller owns the commit (mirrors how routes commit the freshly-created
        session). Idempotent — safe to call on an existing chronicle."""
        existing = await self.load_for_session(db, session.id)
        if existing is not None:
            return existing
        start = self.settings.sheet_attribute_start
        hp = self.settings.sheet_hp_start
        sheet = CharacterSheet(
            session_id=session.id,
            might=start,
            finesse=start,
            wits=start,
            presence=start,
            level=1,
            xp=0,
            hp=hp,
            max_hp=hp,
        )
        db.add(sheet)
        await db.flush()
        return sheet

    def _clamp_attr(self, value: int) -> int:
        return max(self.settings.sheet_attribute_min, min(self.settings.sheet_attribute_max, value))

    def _pick_bump(self, sheet: CharacterSheet, attribute_key: str | None) -> str | None:
        """Which attribute to raise on level-up: the triggering check's attribute
        when it isn't already capped, else the currently-lowest attribute (rounds
        the character out for attribute-less quest XP). ``None`` if all capped."""
        cap = self.settings.sheet_attribute_max
        key = (attribute_key or "").strip().lower()
        if key in ATTRIBUTE_KEYS and getattr(sheet, key) < cap:
            return key
        candidates = [k for k in ATTRIBUTE_KEYS if getattr(sheet, k) < cap]
        if not candidates:
            return None
        return min(candidates, key=lambda k: getattr(sheet, k))

    async def grant_xp(
        self,
        db: AsyncSession,
        session_id: str,
        amount: int,
        *,
        attribute_key: str | None = None,
        reason: str = "",
    ) -> LevelUpResult | None:
        """Add ``amount`` XP to the session's sheet and apply any resulting
        level-ups (each bumps one attribute). Returns a :class:`LevelUpResult`
        when at least one level was gained, else ``None`` (also ``None`` when the
        session has no sheet). Commits its own write; best-effort — any failure is
        logged and swallowed so it never breaks the turn (repo convention).

        The sheet is re-read **under a row lock** (``FOR UPDATE``) rather than
        trusting a caller-supplied instance: the sheet has no version column like
        the world-state ledger, so without the lock two overlapping turns on the
        same chronicle would read-modify-write and lose an XP grant. ``populate_existing``
        forces a fresh read even if this session already cached the row (e.g. the
        pre-roll modifier load in the orchestrator)."""
        if amount <= 0:
            return None
        with tracer.start_as_current_span("character_sheet.grant_xp") as span:
            span.set_attribute("rpg.session_id", str(session_id))
            span.set_attribute("rpg.sheet.xp_amount", amount)
            span.set_attribute("rpg.sheet.reason", reason)
            sheet = await db.scalar(
                select(CharacterSheet)
                .where(CharacterSheet.session_id == session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if sheet is None:
                return None
            old_level = sheet.level
            sheet.xp += amount
            target_level = self.level_for_xp(sheet.xp)
            bumps: list[tuple[str, int]] = []
            while sheet.level < target_level:
                sheet.level += 1
                attr = self._pick_bump(sheet, attribute_key)
                if attr is not None:
                    new_value = self._clamp_attr(getattr(sheet, attr) + 1)
                    setattr(sheet, attr, new_value)
                    bumps.append((attr, new_value))
                    attribute_bumps.add(1, {"attribute": attr})
            try:
                await db.commit()
            except SQLAlchemyError:
                logger.exception("character-sheet xp grant failed for session=%s", session_id)
                await db.rollback()
                return None
            xp_granted.add(amount, {"reason": reason or "unspecified"})
            if sheet.level > old_level:
                level_ups.add(sheet.level - old_level)
                span.set_attribute("rpg.sheet.new_level", sheet.level)
                return LevelUpResult(old_level=old_level, new_level=sheet.level, bumps=bumps)
            return None

    # --- HP / resources (todo-rpg Phase 3) -------------------------------
    def damage_for_stakes(self, stakes: str | None) -> int:
        """Flat, deterministic HP cost for a failed check's severity tag. The GM
        proposes the band (minor/major); the engine owns the number — no
        hallucinated damage, mirroring how the DC band works for the roll."""
        key = (stakes or "").strip().lower()
        if key == "major":
            return self.settings.hp_damage_major
        if key == "minor":
            return self.settings.hp_damage_minor
        return 0

    async def _change_hp(
        self,
        db: AsyncSession,
        session_id: str,
        delta: int,
        *,
        permadeath: bool,
        reason: str,
    ) -> HpChangeResult | None:
        """Apply a signed HP ``delta`` (clamped to ``[0, max_hp]``) under a row
        lock, returning the outcome. ``None`` when there's no sheet or no change.
        Best-effort: commits its own write, swallows failures (repo convention)."""
        if delta == 0:
            return None
        with tracer.start_as_current_span("character_sheet.change_hp") as span:
            span.set_attribute("rpg.session_id", str(session_id))
            span.set_attribute("rpg.sheet.hp_delta", delta)
            span.set_attribute("rpg.sheet.reason", reason)
            sheet = await db.scalar(
                select(CharacterSheet)
                .where(CharacterSheet.session_id == session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if sheet is None:
                return None
            new_hp = max(0, min(sheet.max_hp, sheet.hp + delta))
            applied = new_hp - sheet.hp
            if applied == 0:  # already at the clamp (full HP heal / downed taking more)
                return None
            sheet.hp = new_hp
            downed = new_hp == 0
            died = downed and permadeath
            try:
                await db.commit()
            except SQLAlchemyError:
                logger.exception("character-sheet hp change failed for session=%s", session_id)
                await db.rollback()
                return None
            if applied < 0:
                hp_damage.add(-applied, {"reason": reason or "unspecified"})
            else:
                hp_healed.add(applied, {"reason": reason or "unspecified"})
            if downed:
                sheet_downs.add(1, {"permadeath": str(died).lower()})
                span.set_attribute("rpg.sheet.downed", True)
            return HpChangeResult(amount=applied, hp=new_hp, max_hp=sheet.max_hp, downed=downed, died=died)

    async def apply_damage(
        self, db: AsyncSession, session_id: str, amount: int, *, permadeath: bool, reason: str = "check"
    ) -> HpChangeResult | None:
        """Subtract ``amount`` HP (no-op for amount <= 0)."""
        if amount <= 0:
            return None
        return await self._change_hp(db, session_id, -amount, permadeath=permadeath, reason=reason)

    async def apply_heal(
        self, db: AsyncSession, session_id: str, amount: int, *, reason: str = "rest"
    ) -> HpChangeResult | None:
        """Add ``amount`` HP, clamped to max (no-op for amount <= 0). Healing never
        triggers death, so permadeath is irrelevant here."""
        if amount <= 0:
            return None
        return await self._change_hp(db, session_id, amount, permadeath=False, reason=reason)

    def rest_heal_amount(self, sheet: CharacterSheet) -> int:
        """HP a rest restores: a fraction of max (never a free full reset)."""
        return max(1, round(sheet.max_hp * self.settings.hp_rest_heal_fraction))
