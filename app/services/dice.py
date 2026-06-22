"""Server-side d20 skill checks (§4c).

Pure, deterministic-when-seeded resolution so the math never lives in an LLM.
Competence is DC-only (there is no character stat block) — the GM picks the DC
upstream; here we just roll and classify. Outcomes are ``critical_success``
(nat 20), ``success`` (die >= dc), or ``failure``. There is intentionally no
critical-failure tier: a nat 1 is simply a failure (matches D&D 5e RAW for
ability checks, and avoids punishing competent characters with slapstick).
"""

from __future__ import annotations

import random

CRITICAL_SUCCESS = "critical_success"
SUCCESS = "success"
FAILURE = "failure"

DIE_SIDES = 20
# Clamp GM-proposed DCs to a sane d20 band: DC 2 fails only on a nat 1
# ("very easy"); DC 20 succeeds only on 20+ ("nearly impossible").
DC_MIN = 2
DC_MAX = 20


def clamp_dc(dc: int) -> int:
    """Keep a GM-proposed DC inside the playable d20 band."""
    return max(DC_MIN, min(DC_MAX, dc))


def roll_check(dc: int, *, rng: random.Random | None = None) -> tuple[int, str]:
    """Roll a d20 against ``dc``; return ``(die, outcome)``.

    ``rng`` is injectable for deterministic tests; defaults to the module RNG.
    """
    r = rng or random
    die = r.randint(1, DIE_SIDES)
    if die == DIE_SIDES:
        outcome = CRITICAL_SUCCESS
    elif die >= dc:
        outcome = SUCCESS
    else:
        outcome = FAILURE
    return die, outcome


def message_may_need_check(message: str) -> bool:
    """Cheap, no-LLM pre-filter for whether a player message is worth sending to
    the (costly) per-turn ``assess_action`` call.

    Deliberately conservative — it only skips when we're confident no check is
    needed, so it never swallows a real action; ``assess_action`` still makes the
    final decision on everything that passes. Skips empty input and a single,
    self-contained question (asking the GM something is not attempting an action).
    A message with more than one sentence, or not phrased as a question, passes.
    """
    text = message.strip()
    if not text:
        return False
    # "?" with no other sentence terminator ≈ one bare question, e.g.
    # "what do the blue lanterns mean?". "I sneak in. Is it locked?" keeps its
    # "." and so still gets assessed.
    if text.endswith("?") and "." not in text and "!" not in text:
        return False
    return True


def roll_directive(skill_label: str, dc: int, die: int, outcome: str) -> str:
    """Prompt fragment injected into narration/actor context so the generated
    prose respects the roll instead of inventing its own outcome."""
    verdict = {
        CRITICAL_SUCCESS: "a CRITICAL SUCCESS — they succeed spectacularly, beyond what was attempted",
        SUCCESS: "a SUCCESS",
        FAILURE: "a FAILURE",
    }[outcome]
    return (
        f"[Skill check] The player attempted a {skill_label} check (DC {dc}). "
        f"They rolled {die} on a d20 — {verdict}. "
        "Narrate the outcome consistent with this result; do not contradict the roll."
    )
