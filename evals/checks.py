"""Reusable structural checks for eval cases.

Each factory returns a ``StructuralCheck``: ``(parsed) -> (passed, detail)``.
Checks are forgiving about the exact JSON shape small models emit (missing keys
treated as empty) but strict about the signal under test.
"""

from __future__ import annotations

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


def quest_stage_completed() -> StructuralCheck:
    def _check(parsed: object) -> tuple[bool, str]:
        p = parsed if isinstance(parsed, dict) else {}
        for q in p.get("quests_update") or []:
            if q.get("stages_complete"):
                return True, "stage marked complete"
        return False, "no stage marked complete"

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
