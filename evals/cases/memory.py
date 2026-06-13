"""Memory-extraction cases: durable facts and relationships are captured, while
small talk is ignored."""

from __future__ import annotations

from evals.checks import facts_empty_or_low, facts_nonempty, relationships_nonempty
from evals.harness import EvalCase, Target

CASES = [
    EvalCase(
        id="memory-extracts-explicit-promise",
        category="memory",
        target=Target.MEMORY,
        inputs={
            "transcript": (
                "USER: Maren, I swear it — I'll carry your sister's letter to the lighthouse at Saltcliff "
                "and put it in her hands myself.\n"
                "ASSISTANT: Maren presses the sealed letter into your palm, her eyes wet. "
                '"Saltcliff. The keeper there is named Ysolde. Tell her Maren still waits."'
            ),
        },
        structural=[facts_nonempty()],
        rubric=(
            "The extracted facts must record that the player promised to deliver Maren's sister's "
            "letter to the lighthouse at Saltcliff. Capturing the destination (Saltcliff/lighthouse) "
            "or the keeper Ysolde also counts. PASS if the promise to deliver the letter is recorded."
        ),
        max_tokens=600,
    ),
    EvalCase(
        id="memory-ignores-small-talk",
        category="memory",
        target=Target.MEMORY,
        inputs={
            "transcript": (
                "USER: Nice weather today, huh?\n"
                "ASSISTANT: The innkeeper shrugs. \"Same as yesterday. Bit of cloud, bit of sun.\"\n"
                "USER: Yeah. Anyway.\n"
                "ASSISTANT: He wipes a mug and goes back to humming an old tune."
            ),
        },
        structural=[facts_empty_or_low()],
        max_tokens=400,
    ),
    EvalCase(
        id="memory-captures-relationship-shift",
        category="memory",
        target=Target.MEMORY,
        inputs={
            "transcript": (
                "USER: I haul the wounded scout, Dren, out of the river and bind his leg.\n"
                "ASSISTANT: Dren coughs up water, gripping your arm. "
                '"You didn\'t have to do that. I won\'t forget it. From here on, my blade is yours."'
            ),
        },
        structural=[relationships_nonempty()],
        rubric=(
            "The output must record a relationship where Dren is now an ally of, loyal to, or "
            "indebted to the player after being rescued. PASS if such a relationship is present."
        ),
        max_tokens=600,
    ),
]
