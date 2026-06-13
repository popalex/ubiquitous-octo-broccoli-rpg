"""Memory-extraction cases: durable facts and relationships are captured, while
small talk is ignored."""

from __future__ import annotations

from evals.checks import facts_empty_or_low, facts_mention, facts_nonempty, relationship_with_player
from evals.harness import EvalCase, Target

# These cases use deterministic structural checks rather than the LLM judge: the
# extractions here are structurally verifiable (a fact mentioning the
# destination, a relationship linking the right parties), and on a small model
# the judge just adds noise — it flapped pass/fail on a stably-correct answer.
# The LLM judge is reserved for prose constraints (see gm_narration).

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
        # The durable fact is the delivery destination; the model reliably names
        # Saltcliff / the lighthouse / Ysolde.
        structural=[facts_nonempty(), facts_mention(["saltcliff", "lighthouse", "ysolde"])],
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
        # The signal is a captured relationship linking Dren and the player; the
        # exact status label ("owed allegiance", "loyal", ...) doesn't matter.
        structural=[relationship_with_player("Dren")],
        max_tokens=600,
    ),
]
