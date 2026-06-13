"""World-state ledger cases: deltas record real changes, stay empty when nothing
changed, and never undo established canon (the dead stay dead)."""

from __future__ import annotations

import json

from evals.checks import (
    entity_not_resurrected,
    entity_status,
    has_inventory_change,
    ledger_unchanged_after_apply,
)
from evals.harness import EvalCase, Target

_EMPTY_LEDGER = json.dumps({"location": None, "entities": [], "inventory": [], "threads": [], "facts": []})

_LEDGER_WITH_DEAD_KAEL = json.dumps(
    {
        "location": {"name": "Ashfall Keep", "description": "A ruined fortress."},
        "entities": [
            {"id": "kael", "name": "Kael", "kind": "npc", "status": "dead", "facts": ["Slain by the warden."]}
        ],
        "inventory": [{"item": "torch", "qty": 2}],
        "threads": [],
        "facts": ["The warden guards the inner gate."],
    }
)

CASES = [
    EvalCase(
        id="world-records-a-death",
        category="world_state",
        target=Target.WORLD_STATE,
        inputs={
            "ledger_json": _EMPTY_LEDGER,
            "user_message": "I drive my sword through the bandit captain's chest.",
            "gm_response": (
                "The bandit captain, Voss, staggers, then collapses. He does not rise again — "
                "the firelight catches his unseeing eyes."
            ),
        },
        structural=[entity_status("voss", "dead")],
        max_tokens=800,
    ),
    EvalCase(
        id="world-records-item-pickup",
        category="world_state",
        target=Target.WORLD_STATE,
        inputs={
            "ledger_json": _EMPTY_LEDGER,
            "user_message": "I pry the rusted iron key from the skeleton's grip and pocket it.",
            "gm_response": "The bones crumble. The cold iron key is yours now, heavy with old rust.",
        },
        structural=[has_inventory_change()],
        max_tokens=800,
    ),
    EvalCase(
        id="world-no-material-change-on-noop-turn",
        category="world_state",
        target=Target.WORLD_STATE,
        inputs={
            "ledger_json": _LEDGER_WITH_DEAD_KAEL,
            "user_message": "I look around the keep and take a slow breath.",
            "gm_response": "Dust drifts in the broken light. Nothing stirs in the silent hall.",
        },
        # A description-only turn must not move the ledger. The ideal output is
        # {}, but a small model harmlessly restating the unchanged location or
        # dead entity is fine — what must NOT happen is a real change (a phantom
        # inventory decrement, flavor text becoming a fact). Measured through the
        # real apply path, which is also where the service's no-op guard lives.
        structural=[ledger_unchanged_after_apply(_LEDGER_WITH_DEAD_KAEL)],
        max_tokens=600,
    ),
    EvalCase(
        id="world-does-not-resurrect-the-dead",
        category="world_state",
        target=Target.WORLD_STATE,
        inputs={
            "ledger_json": _LEDGER_WITH_DEAD_KAEL,
            "user_message": "I kneel by Kael's body and whisper that I'm sorry.",
            "gm_response": "Kael's body lies still and cold. Your apology goes unanswered in the empty keep.",
        },
        structural=[entity_not_resurrected("kael")],
        max_tokens=600,
    ),
]
