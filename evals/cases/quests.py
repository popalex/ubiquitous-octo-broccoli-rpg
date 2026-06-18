"""Quest-judge cases: create quests for real commitments, advance them when the
fiction moves, and don't invent quests from idle chatter.

Exercised through the unified post-turn judge (quest-only section) — the sole
production extraction path — so output nests under ``quest_delta`` and the
checks dig in via ``in_section``."""

from __future__ import annotations

import json

from evals.checks import in_section, no_quest_created, quest_created, quest_progressed, quest_status
from evals.harness import EvalCase, Target

_NO_OPEN_QUESTS = json.dumps([])

_OFFERED_QUEST = json.dumps(
    [
        {
            "slug": "find-marens-sister",
            "title": "The Letter to Saltcliff",
            "quest_type": "promise",
            "description": "Maren asked you to find her lost sister.",
            "status": "offered",
            "stages": [
                {"id": "reach-saltcliff", "description": "Travel to the lighthouse at Saltcliff."},
                {"id": "find-ysolde", "description": "Find the keeper, Ysolde."},
            ],
        }
    ]
)

CASES = [
    EvalCase(
        id="quest-created-from-explicit-promise",
        category="quests",
        target=Target.POST_TURN_JUDGE,
        inputs={
            "world": False,
            "quests": True,
            "open_quests_json": _NO_OPEN_QUESTS,
            "user_message": (
                "I kneel and tell the widow: I'll find who burned your farm, and I'll make them answer for it."
            ),
            "gm_response": ("The widow's hands tremble. \"Their banner was a red hawk. That's all I saw.\""),
        },
        # The signal is that a quest is created from a real commitment; the
        # type taxonomy is fuzzy (a revenge vow reads as promise OR mystery), so
        # don't pin the exact quest_type.
        structural=[in_section("quest_delta", quest_created())],
        max_tokens=1100,
    ),
    EvalCase(
        id="quest-not-created-from-idle-chatter",
        category="quests",
        target=Target.POST_TURN_JUDGE,
        inputs={
            "world": False,
            "quests": True,
            "open_quests_json": _NO_OPEN_QUESTS,
            "user_message": "I order another ale and ask the bard to play something cheerful.",
            "gm_response": "The bard grins and strikes up a jaunty reel. The tavern warms with the tune.",
        },
        structural=[in_section("quest_delta", no_quest_created())],
        max_tokens=1100,
    ),
    EvalCase(
        id="quest-advances-when-milestone-reached",
        category="quests",
        target=Target.POST_TURN_JUDGE,
        inputs={
            "world": False,
            "quests": True,
            "open_quests_json": _OFFERED_QUEST,
            "user_message": "After days on the coast road, I finally reach the lighthouse at Saltcliff.",
            "gm_response": (
                "The Saltcliff lighthouse rises before you, salt-scoured and grey. "
                "You've arrived. A figure watches from the gallery above."
            ),
        },
        # Reaching Saltcliff completes the "reach-saltcliff" stage; the model
        # records that either as a completed stage or a progress note.
        structural=[in_section("quest_delta", quest_progressed("find-marens-sister"))],
        max_tokens=1100,
    ),
    EvalCase(
        id="quest-activated-when-player-engages",
        category="quests",
        target=Target.POST_TURN_JUDGE,
        inputs={
            "world": False,
            "quests": True,
            "open_quests_json": _OFFERED_QUEST,
            "user_message": "I tell Maren I'll do it — I'll find your sister. Point me to Saltcliff.",
            "gm_response": 'Maren exhales, relief flooding her face. "The coast road, three days east. Thank you."',
        },
        structural=[in_section("quest_delta", quest_status("find-marens-sister", "active"))],
        max_tokens=1100,
    ),
]
