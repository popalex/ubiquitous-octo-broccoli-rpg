"""Quest-judge cases: create quests for real commitments, advance them when the
fiction moves, and don't invent quests from idle chatter."""

from __future__ import annotations

import json

from evals.checks import no_quest_created, quest_created, quest_stage_completed, quest_status
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
        target=Target.QUESTS,
        inputs={
            "open_quests_json": _NO_OPEN_QUESTS,
            "user_message": (
                "I kneel and tell the widow: I'll find who burned your farm, "
                "and I'll make them answer for it."
            ),
            "gm_response": (
                "The widow's hands tremble. \"Their banner was a red hawk. That's all I saw.\""
            ),
        },
        structural=[quest_created(quest_type="promise")],
        max_tokens=700,
    ),
    EvalCase(
        id="quest-not-created-from-idle-chatter",
        category="quests",
        target=Target.QUESTS,
        inputs={
            "open_quests_json": _NO_OPEN_QUESTS,
            "user_message": "I order another ale and ask the bard to play something cheerful.",
            "gm_response": "The bard grins and strikes up a jaunty reel. The tavern warms with the tune.",
        },
        structural=[no_quest_created()],
        max_tokens=500,
    ),
    EvalCase(
        id="quest-stage-completed-when-fiction-shows-it",
        category="quests",
        target=Target.QUESTS,
        inputs={
            "open_quests_json": _OFFERED_QUEST,
            "user_message": "After days on the coast road, I finally reach the lighthouse at Saltcliff.",
            "gm_response": (
                "The Saltcliff lighthouse rises before you, salt-scoured and grey. "
                "You've arrived. A figure watches from the gallery above."
            ),
        },
        structural=[quest_stage_completed()],
        max_tokens=700,
    ),
    EvalCase(
        id="quest-activated-when-player-engages",
        category="quests",
        target=Target.QUESTS,
        inputs={
            "open_quests_json": _OFFERED_QUEST,
            "user_message": "I tell Maren I'll do it — I'll find your sister. Point me to Saltcliff.",
            "gm_response": "Maren exhales, relief flooding her face. \"The coast road, three days east. Thank you.\"",
        },
        structural=[quest_status("find-marens-sister", "active")],
        max_tokens=700,
    ),
]
