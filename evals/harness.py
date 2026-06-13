"""Core eval harness: case definition, prompt assembly, and the runner.

The message builders below mirror the real service call sites so evals exercise
the exact prompt the app ships. Each builder names its source service; if a
service changes how it assembles its user block, update the matching builder
here (the duplication is deliberate — it keeps evals dependency-free of the DB
layer those services otherwise require).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from app.prompts import (
    CONTINUITY_CHECK_PROMPT,
    GM_NARRATION_PROMPT,
    GM_SYSTEM_PROMPT,
    MEMORY_EXTRACT_PROMPT,
    QUEST_JUDGE_PROMPT,
    WORLD_STATE_EXTRACT_PROMPT,
)
from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
from evals.judge import judge


class Target(StrEnum):
    """Which prompt path a case exercises."""

    CONTINUITY = "continuity"
    MEMORY = "memory"
    WORLD_STATE = "world_state"
    QUESTS = "quests"
    GM_NARRATION = "gm_narration"


# A structural check inspects the parsed output and returns (passed, detail).
# For JSON targets the argument is the parsed dict; for GM narration it is the
# raw narration string.
StructuralCheck = Callable[[object], tuple[bool, str]]

# Targets that return free text rather than JSON.
_TEXT_TARGETS = {Target.GM_NARRATION}


def build_messages(target: Target, inputs: dict) -> list[ProviderMessage]:
    """Assemble the provider messages for a case, mirroring the real service."""
    if target is Target.CONTINUITY:
        # Mirrors ContinuityService.validate (app/services/continuity.py).
        return [
            ProviderMessage(role="system", content=CONTINUITY_CHECK_PROMPT),
            ProviderMessage(
                role="user",
                content=(
                    f"Hard rules:\n{inputs['hard_rules']}\n\n"
                    f"World canon:\n{inputs['world_canon']}\n\n"
                    f"Recent transcript:\n{inputs['recent_transcript']}\n\n"
                    f"User message:\n{inputs['user_message']}\n\n"
                    f"Draft reply:\n{inputs['draft_reply']}"
                ),
            ),
        ]
    if target is Target.MEMORY:
        # Mirrors MemoryService.maybe_refresh -> _format_turns
        # (app/services/memory.py): the user block is the raw transcript.
        return [
            ProviderMessage(role="system", content=MEMORY_EXTRACT_PROMPT),
            ProviderMessage(role="user", content=inputs["transcript"]),
        ]
    if target is Target.WORLD_STATE:
        # Mirrors WorldStateService.extract_and_apply (app/services/world_state.py).
        return [
            ProviderMessage(role="system", content=WORLD_STATE_EXTRACT_PROMPT),
            ProviderMessage(
                role="user",
                content=(
                    f"CURRENT LEDGER:\n{inputs['ledger_json']}\n\n"
                    f"LATEST EXCHANGE:\nPLAYER: {inputs['user_message']}\n"
                    f"RESPONSE: {inputs['gm_response']}"
                ),
            ),
        ]
    if target is Target.QUESTS:
        # Mirrors QuestService.extract_and_apply (app/services/quests.py).
        return [
            ProviderMessage(role="system", content=QUEST_JUDGE_PROMPT),
            ProviderMessage(
                role="user",
                content=(
                    f"OPEN QUESTS:\n{inputs['open_quests_json']}\n\n"
                    f"LATEST EXCHANGE:\nPLAYER: {inputs['user_message']}\n"
                    f"RESPONSE: {inputs['gm_response']}"
                ),
            ),
        ]
    if target is Target.GM_NARRATION:
        # Mirrors GameMasterService.generate_narration (app/services/game_master.py).
        system_prompt = GM_SYSTEM_PROMPT.format(
            world_name=inputs.get("world_name", "Unknown World"),
            world_description=inputs.get("world_description", "A mysterious realm."),
            world_canon=inputs.get("world_canon", ""),
            hard_rules=inputs.get("hard_rules", "None specified."),
            active_characters=inputs.get("active_characters", "None specified."),
            scene_context=inputs.get("scene_context", "Scene not established."),
        )
        user_prompt = GM_NARRATION_PROMPT.format(
            recent_events=inputs["recent_events"],
            player_action=inputs["player_action"],
        )
        return [
            ProviderMessage(role="system", content=system_prompt),
            ProviderMessage(role="user", content=user_prompt),
        ]
    raise ValueError(f"unknown eval target: {target}")


@dataclass(slots=True)
class EvalCase:
    """One golden case. ``structural`` checks run against the parsed output;
    if ``rubric`` is set, an LLM judge also scores the output pass/fail."""

    id: str
    category: str
    target: Target
    inputs: dict
    structural: list[StructuralCheck] = field(default_factory=list)
    rubric: str | None = None
    temperature: float = 0.1
    max_tokens: int = 600


@dataclass(slots=True)
class EvalResult:
    case_id: str
    category: str
    passed: bool
    detail: str


async def run_case(
    case: EvalCase,
    provider: BaseModelProvider,
    judge_provider: BaseModelProvider,
) -> EvalResult:
    """Run one case end-to-end: build messages, call the model, score it."""
    messages = build_messages(case.target, case.inputs)
    failures: list[str] = []

    if case.target in _TEXT_TARGETS:
        parsed: object = await provider.generate_text(
            messages, temperature=case.temperature, max_tokens=case.max_tokens
        )
        output_text = str(parsed)
    else:
        try:
            parsed = await provider.generate_json(
                messages, temperature=case.temperature, max_tokens=case.max_tokens
            )
        except ProviderError as exc:
            return EvalResult(case.id, case.category, False, f"provider returned invalid JSON: {exc}")
        output_text = json.dumps(parsed, ensure_ascii=False)

    for check in case.structural:
        ok, detail = check(parsed)
        if not ok:
            failures.append(f"structural: {detail}")

    if case.rubric:
        verdict = await judge(judge_provider, rubric=case.rubric, output=output_text)
        if verdict.verdict != "pass":
            label = "judge inconclusive" if verdict.verdict == "error" else "judge"
            failures.append(f"{label}: {verdict.reason}")

    return EvalResult(case.id, case.category, not failures, "; ".join(failures) or "ok")


# Convenience for the runner: also expose Awaitable type for callers that want
# to type-annotate run_case results without importing the dataclass directly.
RunCase = Callable[[EvalCase, BaseModelProvider, BaseModelProvider], Awaitable[EvalResult]]
