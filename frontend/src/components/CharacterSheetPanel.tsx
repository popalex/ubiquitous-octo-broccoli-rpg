import { Brain, Hand, Heart, MessageCircle, Moon, Skull, Sword } from "lucide-react";

import type { CharacterSheet } from "../types";

type Props = {
  sheet: CharacterSheet | null;
  /** True when the chronicle has ended (permadeath + 0 HP). */
  dead?: boolean;
  onRest?: () => void;
  resting?: boolean;
};

const ATTRIBUTES = [
  { key: "might", label: "Might", Icon: Sword },
  { key: "finesse", label: "Finesse", Icon: Hand },
  { key: "wits", label: "Wits", Icon: Brain },
  { key: "presence", label: "Presence", Icon: MessageCircle },
] as const;

/** Read-only character sheet (todo-rpg Phases 1–3): the four flat-modifier
 * attributes, HP (with a Rest action), level, and an XP progress bar. Competence
 * the d20 check rolls against + the resources a failed check costs. */
export function CharacterSheetPanel({ sheet, dead = false, onRest, resting = false }: Props) {
  const downed = !!sheet && sheet.hp <= 0;
  const atFullHp = !!sheet && sheet.hp >= sheet.max_hp;
  const hpPct = sheet ? (100 * sheet.hp) / sheet.max_hp : 0;

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

          {/* HP (todo-rpg Phase 3) */}
          <div className="sheet-hp">
            <div className="sheet-hp-meta">
              <span className={`sheet-hp-label${downed ? " sheet-hp-downed" : ""}`}>
                {dead ? <Skull className="inline-icon" /> : <Heart className="inline-icon" />}{" "}
                {dead ? "Fallen" : downed ? "Downed" : "HP"}
              </span>
              <span className="muted">
                {sheet.hp} / {sheet.max_hp}
              </span>
            </div>
            <div
              className="sheet-hp-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={sheet.max_hp}
              aria-valuenow={sheet.hp}
            >
              <div className="sheet-hp-fill" style={{ width: `${hpPct}%` }} />
            </div>
            {onRest && (
              <button
                type="button"
                className="sheet-rest-btn"
                onClick={onRest}
                disabled={resting || dead || atFullHp}
                title={
                  dead
                    ? "This chronicle has ended"
                    : atFullHp
                      ? "Already at full health"
                      : "Rest to recover HP — but the world moves on while you do"
                }
              >
                <Moon className="inline-icon" /> {resting ? "Resting…" : "Rest"}
              </button>
            )}
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
