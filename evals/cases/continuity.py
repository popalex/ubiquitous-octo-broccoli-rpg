"""Continuity-check cases: does the checker catch canon violations without
firing on clean drafts?"""

from __future__ import annotations

from evals.checks import continuity_clean, continuity_flags
from evals.harness import EvalCase, Target

CASES = [
    EvalCase(
        id="continuity-catches-dead-character-speaking",
        category="continuity",
        target=Target.CONTINUITY,
        inputs={
            "hard_rules": "Kael died in the collapse of the Iron Bridge and cannot speak or act.",
            "world_canon": "Kael, the party's guide, was crushed when the Iron Bridge fell two days ago.",
            "recent_transcript": (
                "PLAYER: We lay stones over Kael's grave.\n"
                "ACTOR: The cold wind carries your grief across the gorge."
            ),
            "user_message": "Is there anyone left who can guide us north?",
            "draft_reply": '"I can take you north," Kael says, clapping a warm hand on your shoulder.',
        },
        structural=[continuity_flags()],
        max_tokens=500,
    ),
    EvalCase(
        id="continuity-passes-consistent-draft",
        category="continuity",
        target=Target.CONTINUITY,
        inputs={
            "hard_rules": "Mara is a blacksmith. She never leaves the village of Hollowmere.",
            "world_canon": "Mara forges tools at her smithy in Hollowmere and distrusts outsiders.",
            "recent_transcript": (
                "PLAYER: I show Mara the broken blade.\n"
                "ACTOR: She turns it over, frowning at the shattered tang."
            ),
            "user_message": "Can you reforge it?",
            "draft_reply": (
                "Mara grunts and sets the blade on her anvil. "
                '"Costs you. Outsiders always think iron is free."'
            ),
        },
        structural=[continuity_clean()],
        max_tokens=500,
    ),
    EvalCase(
        id="continuity-catches-spent-gold-the-party-lacks",
        category="continuity",
        target=Target.CONTINUITY,
        inputs={
            "hard_rules": "The party has 0 gold and no valuables to trade.",
            "world_canon": "After the bandit ambush, the party was robbed of every coin.",
            "recent_transcript": (
                "PLAYER: How much do we have left?\n"
                "ACTOR: You turn out empty pockets — not a single coin."
            ),
            "user_message": "I want to buy the silver horse from the trader.",
            "draft_reply": "You count out fifty gold coins and the trader hands you the reins of the silver horse.",
        },
        structural=[continuity_flags()],
        max_tokens=500,
    ),
]
