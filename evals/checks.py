"""Reusable structural checks for eval cases.

Each factory returns a ``StructuralCheck``: ``(parsed) -> (passed, detail)``.
Checks are forgiving about the exact JSON shape small models emit (missing keys
treated as empty) but strict about the signal under test.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from evals.harness import StructuralCheck

# --- continuity --------------------------------------------------------------


def _is_caught(payload: dict) -> bool:
    """The continuity check flagged a problem: ok is false or issues listed."""
    return (not bool(payload.get("ok", True))) or bool(payload.get("issues"))


def continuity_flags() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        if _is_caught(p):
            return True, "violation flagged"
        return False, f"missed violation (ok={p.get('ok')}, issues={p.get('issues')})"

    return _check


def continuity_clean() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        if _is_caught(p):
            return False, f"false positive (issues={p.get('issues')})"
        return True, "clean as expected"

    return _check


# --- world-state ledger ------------------------------------------------------

_DELTA_KEYS = (
    "location",
    "entities_upsert",
    "entities_remove",
    "inventory_changes",
    "threads_upsert",
    "facts_add",
    "facts_remove",
)


def ledger_empty() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        meaningful = [k for k in _DELTA_KEYS if p.get(k)]
        if meaningful:
            return False, f"unexpected delta in {meaningful}"
        return True, "empty delta as expected"

    return _check


def ledger_unchanged_after_apply(ledger_json: str) -> StructuralCheck:
    """The delta, applied to ``ledger_json`` via the real apply path, leaves the
    ledger materially unchanged.

    This is the no-op signal that matters: a small model may harmlessly restate
    the current location or a dead entity (zero applied effect — tolerated), but
    a genuine over-extraction (a phantom inventory change, an invented fact)
    would move the ledger and is still caught. Mirrors the service's own no-op
    guard, which skips writing a version when the applied ledger is unchanged.
    """
    # Imported here to keep the rest of evals/checks dependency-light.
    from app.config import get_settings
    from app.services.world_state import Ledger, LedgerDelta, WorldStateService

    base = Ledger.model_validate(json.loads(ledger_json))
    svc = WorldStateService(None, get_settings())  # apply_delta never touches the provider

    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        try:
            delta = LedgerDelta.model_validate(p)
        except ValidationError as exc:
            return False, f"delta failed schema validation: {exc}"
        applied = svc.apply_delta(base, delta)
        if applied.model_dump() == base.model_dump():
            return True, "ledger materially unchanged after apply"
        return False, "delta materially changed the ledger (real over-extraction)"

    return _check


def entity_status(entity_id: str, status: str) -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        for entity in p.get("entities_upsert", []) or []:
            if entity.get("id") == entity_id and str(entity.get("status", "")).lower() == status:
                return True, f"{entity_id} status={status}"
        return False, f"no entity '{entity_id}' with status '{status}' (got {p.get('entities_upsert')})"

    return _check


def entity_not_resurrected(entity_id: str) -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        for entity in p.get("entities_upsert", []) or []:
            if entity.get("id") == entity_id and str(entity.get("status", "")).lower() == "alive":
                return False, f"{entity_id} wrongly resurrected to alive"
        return True, f"{entity_id} not resurrected"

    return _check


def has_inventory_change() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        changes = p.get("inventory_changes") or []
        return bool(changes), ("inventory changed" if changes else "no inventory_changes recorded")

    return _check


# --- quests ------------------------------------------------------------------


def quest_created(quest_type: str | None = None) -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        new = p.get("quests_new") or []
        if not new:
            return False, "no quest created"
        if quest_type and not any(q.get("quest_type") == quest_type for q in new):
            return False, f"no quest of type '{quest_type}' (got {[q.get('quest_type') for q in new]})"
        return True, "quest created"

    return _check


def no_quest_created() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        new = p.get("quests_new") or []
        if new:
            return False, f"false-positive quest(s): {[q.get('slug') for q in new]}"
        return True, "no quest created, as expected"

    return _check


def quest_status(slug: str, status: str) -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        for q in p.get("quests_update") or []:
            if q.get("slug") == slug and q.get("status") == status:
                return True, f"{slug} -> {status}"
        return False, f"{slug} not set to '{status}' (got {p.get('quests_update')})"

    return _check


def quest_progressed(slug: str | None = None) -> StructuralCheck:
    """The quest advanced — a stage was completed OR progress was noted. Small
    models record a milestone either way, so don't insist on a formal stage."""

    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        for q in p.get("quests_update") or []:
            if slug and q.get("slug") != slug:
                continue
            if q.get("stages_complete") or str(q.get("progress_note", "")).strip():
                return True, "quest progressed"
        return False, f"no progress recorded for {slug or 'any quest'} (got {p.get('quests_update')})"

    return _check


# --- memory ------------------------------------------------------------------


def facts_nonempty() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        facts = [f for f in (p.get("facts") or []) if str(f.get("content", "")).strip()]
        return bool(facts), (f"{len(facts)} fact(s) extracted" if facts else "no facts extracted")

    return _check


def facts_empty_or_low(threshold: float = 0.4) -> StructuralCheck:
    """No durable facts, or only low-importance ones — the small-talk guard."""

    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        facts = [f for f in (p.get("facts") or []) if str(f.get("content", "")).strip()]
        if not facts:
            return True, "no facts, as expected"
        importances = [float(f.get("importance", 0.5) or 0.0) for f in facts]
        if max(importances) < threshold:
            return True, f"only low-importance facts (max {max(importances):.2f})"
        return False, f"extracted notable fact(s) from small talk: {[f.get('content') for f in facts]}"

    return _check


def relationships_nonempty() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        rels = p.get("relationships") or []
        return bool(rels), (f"{len(rels)} relationship(s)" if rels else "no relationships extracted")

    return _check


_PLAYER_ALIASES = ("you", "player", "the player", "i", "me")


def relationship_with_player(entity: str) -> StructuralCheck:
    """A relationship links ``entity`` and the player (either direction)."""

    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        for r in p.get("relationships") or []:
            pair = [str(r.get("source_entity", "")).lower(), str(r.get("target_entity", "")).lower()]
            has_entity = any(entity.lower() in side for side in pair)
            has_player = any(side in _PLAYER_ALIASES or side == "you" for side in pair)
            if has_entity and has_player:
                return True, f"relationship links {entity} and the player"
        return False, f"no {entity}<->player relationship (got {p.get('relationships')})"

    return _check


def facts_mention(keywords: list[str]) -> StructuralCheck:
    """At least one extracted fact mentions one of the keywords (case-insensitive)."""

    kws = [k.lower() for k in keywords]

    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        texts = [str(f.get("content", "")).lower() for f in (p.get("facts") or [])]
        for text in texts:
            if any(k in text for k in kws):
                return True, "a fact mentions the expected detail"
        return False, f"no fact mentions any of {keywords} (facts={texts})"

    return _check
