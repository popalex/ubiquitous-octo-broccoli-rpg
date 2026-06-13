"""CI-safe self-test of the eval plumbing.

These tests use a scripted in-process provider (no network, no real model), so
they run in the default suite and CI. They verify that the harness assembles the
real prompts, dispatches the right provider primitive, runs structural checks,
and folds in the LLM-judge verdict — without asserting anything about model
quality (that's what the ``eval``-marked suite does).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.prompts import CONTINUITY_CHECK_PROMPT, GM_NARRATION_PROMPT
from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
from evals.checks import continuity_flags
from evals.harness import EvalCase, Target, build_messages, run_case


class ScriptedProvider(BaseModelProvider):
    """Returns queued JSON payloads / a fixed text response; optionally raises."""

    def __init__(self, *, json_queue: list[dict] | None = None, text: str = "narration", raise_json: bool = False):
        super().__init__(model_name="scripted")
        self._json_queue = list(json_queue or [])
        self._text = text
        self._raise_json = raise_json

    async def generate_text(self, messages, *, temperature, max_tokens, json_mode=False) -> str:
        return self._text

    async def generate_text_stream(
        self, messages: Sequence[ProviderMessage], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        yield self._text

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def generate_json(self, messages, *, temperature, max_tokens) -> dict:
        if self._raise_json:
            raise ProviderError("scripted invalid JSON")
        return self._json_queue.pop(0) if self._json_queue else {}


def _continuity_case() -> EvalCase:
    return EvalCase(
        id="plumbing-continuity",
        category="continuity",
        target=Target.CONTINUITY,
        inputs={
            "hard_rules": "x",
            "world_canon": "y",
            "recent_transcript": "z",
            "user_message": "q",
            "draft_reply": "r",
        },
        structural=[continuity_flags()],
    )


# --- message assembly --------------------------------------------------------


def test_build_messages_uses_real_prompts() -> None:
    msgs = build_messages(Target.CONTINUITY, _continuity_case().inputs)
    assert len(msgs) == 2
    assert msgs[0].content == CONTINUITY_CHECK_PROMPT
    assert "Draft reply:\nr" in msgs[1].content


def test_build_messages_gm_narration_formats_template() -> None:
    msgs = build_messages(
        Target.GM_NARRATION,
        {"recent_events": "events here", "player_action": "I wait"},
    )
    # The system prompt is the GM system prompt; the user prompt is the narration
    # template with the case fields interpolated.
    assert "Game Master" in msgs[0].content
    assert "events here" in msgs[1].content
    assert GM_NARRATION_PROMPT.split("{", 1)[0].strip() in msgs[1].content


# --- runner: structural checks ----------------------------------------------


async def test_run_case_structural_pass() -> None:
    provider = ScriptedProvider(json_queue=[{"ok": False, "issues": ["contradiction"]}])
    result = await run_case(_continuity_case(), provider, ScriptedProvider())
    assert result.passed, result.detail


async def test_run_case_structural_fail() -> None:
    provider = ScriptedProvider(json_queue=[{"ok": True, "issues": []}])
    result = await run_case(_continuity_case(), provider, ScriptedProvider())
    assert not result.passed
    assert "structural" in result.detail


async def test_run_case_invalid_json_is_a_failure_not_an_error() -> None:
    provider = ScriptedProvider(raise_json=True)
    result = await run_case(_continuity_case(), provider, ScriptedProvider())
    assert not result.passed
    assert "invalid JSON" in result.detail


# --- runner: LLM judge -------------------------------------------------------


def _gm_case() -> EvalCase:
    return EvalCase(
        id="plumbing-gm",
        category="gm_narration",
        target=Target.GM_NARRATION,
        inputs={"recent_events": "e", "player_action": "I look around"},
        rubric="The narration is atmospheric and leaves the player room to act.",
    )


async def test_run_case_judge_pass() -> None:
    provider = ScriptedProvider(text="Fog rolls across the broken road. Something waits, unseen.")
    judge = ScriptedProvider(json_queue=[{"verdict": "pass", "reason": "ok"}])
    result = await run_case(_gm_case(), provider, judge)
    assert result.passed, result.detail


async def test_run_case_judge_fail() -> None:
    provider = ScriptedProvider(text="You decide to run away screaming.")
    judge = ScriptedProvider(json_queue=[{"verdict": "fail", "reason": "controls the player"}])
    result = await run_case(_gm_case(), provider, judge)
    assert not result.passed
    assert "judge: controls the player" in result.detail


async def test_run_case_judge_inconclusive_is_a_failure() -> None:
    provider = ScriptedProvider(text="Some narration.")
    judge = ScriptedProvider(json_queue=[{"verdict": "maybe", "reason": "unsure"}])
    result = await run_case(_gm_case(), provider, judge)
    assert not result.passed
    assert "judge inconclusive" in result.detail


async def test_run_case_combines_structural_and_judge_failures() -> None:
    case = EvalCase(
        id="plumbing-combined",
        category="continuity",
        target=Target.CONTINUITY,
        inputs=_continuity_case().inputs,
        structural=[continuity_flags()],
        rubric="Must explain the contradiction clearly.",
    )
    provider = ScriptedProvider(json_queue=[{"ok": True, "issues": []}])
    judge = ScriptedProvider(json_queue=[{"verdict": "fail", "reason": "no explanation"}])
    result = await run_case(case, provider, judge)
    assert not result.passed
    assert "structural" in result.detail and "judge" in result.detail
