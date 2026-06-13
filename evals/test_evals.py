"""The real-model eval run. Marked ``eval`` so it is excluded from the default
(and CI) collection; run it with ``pytest -m eval`` against a live model."""

from __future__ import annotations

import pytest

from evals.cases import ALL_CASES
from evals.harness import run_case

pytestmark = pytest.mark.eval


@pytest.mark.parametrize("case", ALL_CASES, ids=[c.id for c in ALL_CASES])
async def test_eval_case(case, eval_provider, judge_provider) -> None:
    result = await run_case(case, eval_provider, judge_provider)
    assert result.passed, f"[{result.category}] {result.case_id}: {result.detail}"
