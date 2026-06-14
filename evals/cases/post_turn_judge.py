"""Unified post-turn judge cases (§2): the single combined call must extract the
world-state delta and the quest delta correctly in one shot — the parity gate
vs the split world_state/quests prompts.

Output is nested under ``world_delta`` / ``quest_delta``; the section checks dig
into each via ``in_section`` so they reuse the standalone world/quest checks.
"""

from __future__ import annotations

import json

from evals.checks import (
    entity_status,
    in_section,
    ledger_unchanged_after_apply,
    no_quest_created,
    quest_created,
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
_NO_OPEN_QUESTS = json.dumps([])

CASES = [
    EvalCase(
        id="judge-extracts-death-and-quest-in-one-call",
        category="post_turn_judge",
        target=Target.POST_TURN_JUDGE,
        inputs={
            "world": True,
            "quests": True,
            "ledger_json": _EMPTY_LEDGER,
            "open_quests_json": _NO_OPEN_QUESTS,
            "user_message": (
                "I run the bandit captain Voss through, then kneel by the widow and swear "
                "I'll hunt down whoever burned her farm."
            ),
            "gm_response": (
                "Voss crumples, dead before he hits the ground. The widow clutches your sleeve: "
                '"Their banner was a red hawk."'
            ),
        },
        # One call, both sections correct: Voss recorded dead AND a quest created.
        structural=[
            in_section("world_delta", entity_status("voss", "dead")),
            in_section("quest_delta", quest_created()),
        ],
        max_tokens=1100,
    ),
    EvalCase(
        id="judge-no-op-turn-changes-nothing",
        category="post_turn_judge",
        target=Target.POST_TURN_JUDGE,
        inputs={
            "world": True,
            "quests": True,
            "ledger_json": _LEDGER_WITH_DEAD_KAEL,
            "open_quests_json": _NO_OPEN_QUESTS,
            "user_message": "I look around the keep and take a slow breath.",
            "gm_response": "Dust drifts in the broken light. Nothing stirs in the silent hall.",
        },
        # A description-only turn must move neither section.
        structural=[
            in_section("world_delta", ledger_unchanged_after_apply(_LEDGER_WITH_DEAD_KAEL)),
            in_section("quest_delta", no_quest_created()),
        ],
        max_tokens=1100,
    ),
]
