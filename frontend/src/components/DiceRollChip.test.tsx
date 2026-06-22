import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DiceRoll } from "../types";
import { DiceRollChip } from "./DiceRollChip";

const ROLL: DiceRoll = {
  skill_label: "Stealth",
  dc: 12,
  die: 7,
  outcome: "failure",
  rationale: "nimble rogue, but the guard is alert -> moderate",
};

describe("DiceRollChip", () => {
  it("shows the die, skill, DC, outcome, and rationale", () => {
    render(<DiceRollChip roll={ROLL} />);
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Stealth")).toBeInTheDocument();
    expect(screen.getByText(/vs DC 12/)).toBeInTheDocument();
    expect(screen.getByText(/Failure/)).toBeInTheDocument();
    // The DC-encoded competence is surfaced to the player.
    expect(screen.getByText(/nimble rogue/)).toBeInTheDocument();
  });

  it("labels a nat-20 as a critical success and omits a missing rationale", () => {
    render(<DiceRollChip roll={{ ...ROLL, die: 20, outcome: "critical_success", rationale: null }} />);
    expect(screen.getByText(/Critical Success/)).toBeInTheDocument();
    expect(screen.queryByText(/nimble rogue/)).not.toBeInTheDocument();
  });

  it("carries the outcome on the wrapper class for styling", () => {
    const { container } = render(<DiceRollChip roll={ROLL} />);
    expect(container.querySelector(".dice-roll-failure")).not.toBeNull();
  });
});
