import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../types";
import { ChatPanel } from "./ChatPanel";

// turnsToMessages sets a persisted turn's id to its turn_index (numeric string);
// a live/unsaved streamed message gets a non-numeric id.
const MESSAGES: ChatMessage[] = [
  { id: "1", role: "user", content: "I open the door." },
  { id: "2", role: "assistant", content: "The hinges groan." },
  { id: "live-abc", role: "assistant", content: "A draft stirs the candles." },
];

function renderPanel(overrides: Partial<React.ComponentProps<typeof ChatPanel>> = {}) {
  const props: React.ComponentProps<typeof ChatPanel> = {
    chatMessages: MESSAGES,
    chatInput: "",
    setChatInput: vi.fn(),
    isBusy: false,
    sessionId: "sess-1",
    characterName: "Aria",
    statusText: "ready",
    onSendChat: vi.fn(),
    ...overrides,
  };
  return render(<ChatPanel {...props} />);
}

describe("ChatPanel fork-from-here", () => {
  it("shows a fork button only on persisted turns when onForkFromTurn is provided", () => {
    renderPanel({ onForkFromTurn: vi.fn() });
    // Two persisted messages (ids 1, 2); the live message (id live-abc) is not forkable.
    expect(screen.getAllByRole("button", { name: /fork from here/i })).toHaveLength(2);
  });

  it("renders no fork buttons when onForkFromTurn is omitted", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: /fork from here/i })).not.toBeInTheDocument();
  });

  it("calls onForkFromTurn with the turn index of the clicked message", async () => {
    const onFork = vi.fn();
    renderPanel({ onForkFromTurn: onFork });
    const buttons = screen.getAllByRole("button", { name: /fork from here/i });
    // Second button belongs to the assistant turn with id "2".
    await userEvent.click(buttons[1]);
    expect(onFork).toHaveBeenCalledExactlyOnceWith(2);
  });

  it("shows a busy label on the forking turn and disables the buttons", () => {
    renderPanel({ onForkFromTurn: vi.fn(), forkingTurn: 2 });
    expect(screen.getByRole("button", { name: /forking/i })).toBeDisabled();
    // The other fork button is disabled too while a fork is in flight.
    expect(screen.getByRole("button", { name: /fork from here/i })).toBeDisabled();
  });
});
