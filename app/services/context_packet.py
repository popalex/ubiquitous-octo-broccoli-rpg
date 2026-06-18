"""Actor/GM context-packet assembly.

Builds the token-budgeted prompt context the actor and GM see (canonical world
state, hard rules / canon, continuity corrections, recent turns, retrieved
facts, episode summaries), plus the small text-rendering helpers shared with the
continuity check. Pure and unit-testable: no DB, no providers.
"""

from __future__ import annotations

from app.config import Settings
from app.models import CharacterCard, Turn, WorldState
from app.models import Session as ChatSession


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def recent_turns_text(turns: list[Turn]) -> str:
    return "\n".join(f"{turn.role.upper()}: {turn.content}" for turn in turns)


def continuity_canon(session: ChatSession, world_state_block: str) -> str:
    """Canon text continuity defends: the static world canon plus, when enabled,
    the live ledger (the authoritative source of truth)."""
    canon = session.world_state.canon if session.world_state else ""
    if world_state_block.strip():
        return f"{world_state_block}\n\n{canon}".strip()
    return canon


def hard_rules_text(character: CharacterCard, world: WorldState | None) -> str:
    parts = [character.hard_rules]
    if world is not None:
        if world.hard_rules.strip():
            parts.append(world.hard_rules)
        if world.canon.strip():
            parts.append(f"Canon:\n{world.canon}")
    return "\n\n".join(part for part in parts if part.strip())


class ContextPacketBuilder:
    """Assembles the actor/GM context packet against ``actor_context_budget``."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build(
        self,
        session: ChatSession,
        recent_turns: list[Turn],
        retrieved: list,
        world_state_block: str = "",
        quest_block: str = "",
    ) -> str:
        remaining_budget = self.settings.actor_context_budget
        sections: list[str] = []

        if world_state_block.strip():
            remaining_budget = self._append_section(
                sections, "Canonical World State", world_state_block, remaining_budget, required=True
            )

        if quest_block.strip():
            remaining_budget = self._append_section(sections, "Active Quests", quest_block, remaining_budget)

        hard_rules = hard_rules_text(session.character_card, session.world_state)
        remaining_budget = self._append_section(
            sections, "Hard Rules And Canon", hard_rules, remaining_budget, required=True
        )

        retcon_notes = "\n".join(f"- {turn.retcon_note}" for turn in recent_turns if turn.retcon_note)
        if retcon_notes:
            retcon_body = (
                "Earlier replies contradicted established canon. The corrections below are canon; "
                "quietly conform to them in the narrative without mentioning the mistake:\n"
                f"{retcon_notes}"
            )
            remaining_budget = self._append_section(
                sections, "Continuity Corrections", retcon_body, remaining_budget, required=True
            )

        recent_text = recent_turns_text(recent_turns)
        remaining_budget = self._append_section(sections, "Recent Turns", recent_text, remaining_budget)

        facts = "\n".join(f"- {item.content}" for item in retrieved if item.kind == "fact")
        remaining_budget = self._append_section(sections, "Retrieved Facts", facts, remaining_budget)

        summaries = "\n".join(f"- {item.content}" for item in retrieved if item.kind == "summary")
        self._append_section(sections, "Episode Summaries", summaries, remaining_budget)

        return "\n\n".join(section for section in sections if section.strip())

    def _append_section(
        self, sections: list[str], title: str, body: str, remaining_budget: int, *, required: bool = False
    ) -> int:
        if not body.strip():
            return remaining_budget
        cost = estimate_tokens(body)
        if cost > remaining_budget and not required:
            return remaining_budget
        sections.append(f"{title}:\n{body}")
        return max(0, remaining_budget - cost)
