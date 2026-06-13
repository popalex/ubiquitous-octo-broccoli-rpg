"""LLM-as-judge: a pass/fail verdict against a rubric.

Small local models are unreliable on numeric scales, so the judge returns only
``pass``/``fail`` (plus an internal ``error`` when the judge itself misbehaves —
which the runner treats as a failure, never a silent pass).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage

JUDGE_PROMPT = """
You are a strict evaluator for a roleplay engine's LLM outputs.

You are given a RUBRIC describing what a correct output must satisfy, and the
OUTPUT a model produced. Decide whether the output satisfies every requirement
in the rubric. Judge only against the rubric, nothing else.

Be conservative: if any requirement is clearly unmet, the verdict is "fail".

Return strict JSON with this exact shape:
{"verdict": "pass" or "fail", "reason": "one short sentence"}
""".strip()


@dataclass(slots=True)
class Verdict:
    verdict: str  # "pass" | "fail" | "error"
    reason: str


async def judge(provider: BaseModelProvider, *, rubric: str, output: str) -> Verdict:
    """Ask the judge model whether ``output`` satisfies ``rubric``."""
    try:
        payload = await provider.generate_json(
            [
                ProviderMessage(role="system", content=JUDGE_PROMPT),
                ProviderMessage(role="user", content=f"RUBRIC:\n{rubric}\n\nOUTPUT:\n{output}"),
            ],
            temperature=0.0,
            max_tokens=200,
        )
    except ProviderError as exc:
        return Verdict("error", f"judge provider error: {exc}")

    raw = str(payload.get("verdict", "")).strip().lower()
    reason = str(payload.get("reason", "")).strip()
    if raw not in {"pass", "fail"}:
        return Verdict("error", f"judge returned unexpected verdict: {payload!r}")
    return Verdict(raw, reason)
