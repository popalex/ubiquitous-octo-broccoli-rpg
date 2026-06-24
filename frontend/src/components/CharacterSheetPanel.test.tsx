import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CharacterSheet } from "../types";
import { CharacterSheetPanel } from "./CharacterSheetPanel";

const SHEET: CharacterSheet = {
  might: 2,
  finesse: 1,
  wits: 1,
  presence: 1,
  level: 1,
  xp: 0,
  xp_to_next: 100,
  xp_for_level: 100,
  hp: 12,
  max_hp: 20,
};

describe("CharacterSheetPanel", () => {
  it("renders HP and a working Rest button", () => {
    const onRest = vi.fn();
    render(<CharacterSheetPanel sheet={SHEET} onRest={onRest} />);
    expect(screen.getByText("12 / 20")).toBeInTheDocument();
    const rest = screen.getByRole("button", { name: /rest/i });
    expect(rest).toBeEnabled();
    fireEvent.click(rest);
    expect(onRest).toHaveBeenCalledOnce();
  });

  it("disables Rest at full HP", () => {
    render(<CharacterSheetPanel sheet={{ ...SHEET, hp: 20 }} onRest={vi.fn()} />);
    expect(screen.getByRole("button", { name: /rest/i })).toBeDisabled();
  });

  it("shows Downed at 0 HP but still allows resting to recover", () => {
    render(<CharacterSheetPanel sheet={{ ...SHEET, hp: 0 }} onRest={vi.fn()} />);
    expect(screen.getByText("Downed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rest/i })).toBeEnabled();
  });

  it("shows Fallen and blocks Rest when the chronicle has ended", () => {
    render(<CharacterSheetPanel sheet={{ ...SHEET, hp: 0 }} dead onRest={vi.fn()} />);
    expect(screen.getByText("Fallen")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rest/i })).toBeDisabled();
  });

  it("renders the empty state without a sheet", () => {
    render(<CharacterSheetPanel sheet={null} />);
    expect(screen.getByText(/forged as the chronicle begins/i)).toBeInTheDocument();
  });
});
