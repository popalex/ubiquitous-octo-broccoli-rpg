import { Dices } from "lucide-react";
import type { DiceRoll } from "../types";

const OUTCOME_LABEL: Record<DiceRoll["outcome"], string> = {
  critical_success: "Critical Success",
  success: "Success",
  failure: "Failure",
};

/** Renders a resolved d20 skill check (§4c). Shows the die, the skill + DC, the
 * outcome, and the GM's rationale. With a character sheet (todo-rpg Phase 1) it
 * also shows the attribute modifier arithmetic (die + mod = total); without one
 * the modifier is 0 and only the raw die is shown. */
export function DiceRollChip({ roll }: { roll: DiceRoll }) {
  const hasModifier = roll.modifier !== 0;
  const sign = roll.modifier >= 0 ? "+" : "−";
  const mathText = hasModifier ? `${roll.die} ${sign} ${Math.abs(roll.modifier)} = ${roll.total}` : `${roll.die}`;
  const attrText = roll.attribute ? ` (${roll.attribute.toUpperCase()})` : "";
  return (
    <div
      className={`dice-roll dice-roll-${roll.outcome}`}
      role="group"
      aria-label={`Skill check: ${roll.skill_label}${attrText}, DC ${roll.dc}, rolled ${mathText}, ${OUTCOME_LABEL[roll.outcome]}`}
    >
      <span className="dice-roll-die" aria-hidden="true">
        <Dices className="inline-icon" />
        {hasModifier ? roll.total : roll.die}
      </span>
      <span className="dice-roll-text">
        <span className="dice-roll-headline">
          <strong>
            {roll.skill_label}
            {attrText}
          </strong>{" "}
          vs DC {roll.dc} — {OUTCOME_LABEL[roll.outcome]}
        </span>
        {hasModifier && <span className="dice-roll-math">rolled {mathText}</span>}
        {roll.rationale && <span className="dice-roll-rationale">{roll.rationale}</span>}
      </span>
    </div>
  );
}
