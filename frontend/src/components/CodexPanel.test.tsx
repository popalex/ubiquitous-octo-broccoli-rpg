import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorldStateLedger } from "../types";
import { CodexPanel } from "./CodexPanel";

const LEDGER: WorldStateLedger = {
  session_id: "sess-1",
  version: 7,
  created_at: "2026-06-12T00:00:00Z",
  state: {
    location: { name: "The Sunken Library", description: "shelves drowned in green light" },
    entities: [
      { id: "maren", name: "Maren", kind: "npc", status: "wary ally", relationship_to_player: "owes a debt" },
      { id: "kael", name: "Kael", kind: "npc", status: "dead" },
    ],
    inventory: [
      { item: "storm lantern", qty: 1 },
      { item: "rope", qty: null },
    ],
    threads: [
      { id: "t1", summary: "Find the drowned archive's index", status: "open" },
      { id: "t2", summary: "Already settled", status: "resolved" },
    ],
    facts: ["The library floods at high tide."],
  },
};

describe("CodexPanel", () => {
  it("renders every ledger section from a populated snapshot", () => {
    render(<CodexPanel worldState={LEDGER} />);

    expect(screen.getByText("canon v7")).toBeInTheDocument();
    // Location
    expect(screen.getByText("The Sunken Library")).toBeInTheDocument();
    // Living vs dead split
    expect(screen.getByText("Dramatis Personae")).toBeInTheDocument();
    expect(screen.getByText(/Maren/)).toBeInTheDocument();
    expect(screen.getByText("The Fallen")).toBeInTheDocument();
    expect(screen.getByText(/Kael — dead/)).toBeInTheDocument();
    // Inventory with and without quantities
    expect(screen.getByText(/storm lantern ×1, rope/)).toBeInTheDocument();
    // Only open threads render
    expect(screen.getByText("Find the drowned archive's index")).toBeInTheDocument();
    expect(screen.queryByText("Already settled")).not.toBeInTheDocument();
    // Canon facts
    expect(screen.getByText("The library floods at high tide.")).toBeInTheDocument();
  });

  it("shows the empty-state line when the ledger is missing or blank", () => {
    const { rerender } = render(<CodexPanel worldState={null} />);
    expect(screen.getByText("Canon accretes as the story unfolds...")).toBeInTheDocument();
    expect(screen.queryByText(/canon v/)).not.toBeInTheDocument();

    rerender(<CodexPanel worldState={{ session_id: "s", version: 0, created_at: null, state: {} }} />);
    expect(screen.getByText("Canon accretes as the story unfolds...")).toBeInTheDocument();
  });
});
