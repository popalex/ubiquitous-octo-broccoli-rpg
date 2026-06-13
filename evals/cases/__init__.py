"""Golden eval cases, aggregated into ``ALL_CASES`` for the parametrized run."""

from __future__ import annotations

from evals.cases import continuity, gm_narration, memory, post_turn_judge, quests, world_state
from evals.harness import EvalCase

ALL_CASES: list[EvalCase] = [
    *continuity.CASES,
    *memory.CASES,
    *world_state.CASES,
    *quests.CASES,
    *gm_narration.CASES,
    *post_turn_judge.CASES,
]
