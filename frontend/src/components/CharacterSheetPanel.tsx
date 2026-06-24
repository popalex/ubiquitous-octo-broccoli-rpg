import { Brain, Hand, MessageCircle, Sword } from "lucide-react";

import type { CharacterSheet } from "../types";

type Props = {
  sheet: CharacterSheet | null;
};

const ATTRIBUTES = [
  { key: "might", label: "Might", Icon: Sword },
  { key: "finesse", label: "Finesse", Icon: Hand },
  { key: "wits", label: "Wits", Icon: Brain },
  { key: "presence", label: "Presence", Icon: MessageCircle },
] as const;

/** Read-only character sheet (todo-rpg Phase 1): the four flat-modifier
 * attributes, the level, and an XP progress bar. Competence the d20 check rolls
 * against — improves as the chronicle progresses. */
export function CharacterSheetPanel({ sheet }: Props) {
  return (
    <section className="panel panel-right">
      <div className="panel-header">
        <p className="eyebrow">Character Sheet</p>
        <h2>The Hero</h2>
        {sheet && <span className="muted">level {sheet.level}</span>}
      </div>

      {!sheet ? (
        <p className="muted">A sheet is forged as the chronicle begins…</p>
      ) : (
        <div className="stack">
          <div className="sheet-attributes">
            {ATTRIBUTES.map(({ key, label, Icon }) => (
              <div className="sheet-attribute" key={key}>
                <span className="sheet-attribute-label">
                  <Icon className="inline-icon" /> {label}
                </span>
                <span className="sheet-attribute-value">
                  {sheet[key] >= 0 ? "+" : "−"}
                  {Math.abs(sheet[key])}
                </span>
              </div>
            ))}
          </div>

          <div className="sheet-xp">
            <div className="sheet-xp-meta">
              <span>Level {sheet.level}</span>
              <span className="muted">{sheet.xp_to_next} XP to next</span>
            </div>
            <div
              className="sheet-xp-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={sheet.xp_for_level}
              aria-valuenow={sheet.xp_for_level - sheet.xp_to_next}
            >
              <div
                className="sheet-xp-fill"
                style={{
                  width: `${(100 * (sheet.xp_for_level - sheet.xp_to_next)) / sheet.xp_for_level}%`,
                }}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
