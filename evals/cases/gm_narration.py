"""GM-narration cases: judged on the prompt's constraints — concise atmospheric
prose that respects player agency and leaves an opening to act."""

from __future__ import annotations

from evals.harness import EvalCase, Target

_WORLD = {
    "world_name": "The Mistlands",
    "world_description": "A fog-drowned realm of sunken roads and half-remembered gods.",
    "world_canon": "Iron rusts within a day here. The mist hides things that hunt by sound.",
    "hard_rules": "Never speak, act, or decide for the player's character.",
    "active_characters": "None nearby.",
    "scene_context": "A collapsed stone causeway over black water, mist thick on every side.",
}

CASES = [
    EvalCase(
        id="gm-narration-respects-constraints",
        category="gm_narration",
        target=Target.GM_NARRATION,
        inputs={
            **_WORLD,
            "recent_events": "The player stepped onto the broken causeway, listening to the mist.",
            "player_action": "I creep forward along the causeway, testing each stone before I trust it.",
        },
        rubric=(
            "The narration must satisfy ALL of: (1) it is between 2 and 4 paragraphs of atmospheric "
            "scene prose; (2) it does NOT decide, speak, or narrate the player character's choices, "
            "dialogue, or inner thoughts beyond the action they already stated; (3) it ends with the "
            "situation open, leaving room for the player to act next. PASS only if all three hold."
        ),
        temperature=0.7,
        max_tokens=500,
    ),
    EvalCase(
        id="gm-narration-does-not-control-player",
        category="gm_narration",
        target=Target.GM_NARRATION,
        inputs={
            **_WORLD,
            "recent_events": "A shape moved in the mist ahead; something heavy slid into the water.",
            "player_action": "I freeze and hold my breath, straining to hear where it went.",
        },
        rubric=(
            "The narration must NOT seize control of the player's character: it must not have the "
            "player decide to flee, attack, call out, or feel a specific emotion that wasn't stated. "
            "It may describe the environment, the unseen threat, and sensations the player would "
            "passively perceive. PASS if the player's agency is preserved."
        ),
        temperature=0.7,
        max_tokens=500,
    ),
]
