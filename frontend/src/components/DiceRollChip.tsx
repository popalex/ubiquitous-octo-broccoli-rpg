import { Dices } from "lucide-react";
import type { DiceRoll } from "../types";

const OUTCOME_LABEL: Record<DiceRoll["outcome"], string> = {
  critical_success: "Critical Success",
  success: "Success",
  failure: "Failure",
};

/** Renders a resolved d20 skill check (§4c). Shows the die, the skill + DC, the
 * outcome, and the GM's rationale — competence lives in the DC, so the rationale
 * is what makes that competence visible to the player. */
export function DiceRollChip({ roll }: { roll: DiceRoll }) {
  return (
    <div
      className={`dice-roll dice-roll-${roll.outcome}`}
      role="group"
      aria-label={`Skill check: ${roll.skill_label}, DC ${roll.dc}, rolled ${roll.die}, ${OUTCOME_LABEL[roll.outcome]}`}
    >
      <span className="dice-roll-die" aria-hidden="true">
        <Dices className="inline-icon" />
        {roll.die}
      </span>
      <span className="dice-roll-text">
        <span className="dice-roll-headline">
          <strong>{roll.skill_label}</strong> vs DC {roll.dc} — {OUTCOME_LABEL[roll.outcome]}
        </span>
        {roll.rationale && <span className="dice-roll-rationale">{roll.rationale}</span>}
      </span>
    </div>
  );
}
