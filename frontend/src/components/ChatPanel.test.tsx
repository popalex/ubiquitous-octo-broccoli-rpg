import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../types";
import { ChatPanel } from "./ChatPanel";

// turnsToMessages sets a persisted turn's id to its turn_index (numeric string);
// a live/unsaved streamed message gets a non-numeric id. Forking is offered only
// on persisted *response* turns (assistant/narrator), never on user lines or
// live messages.
const MESSAGES: ChatMessage[] = [
  { id: "1", role: "user", content: "I open the door." },
  { id: "2", role: "assistant", content: "The hinges groan." },
  { id: "3", role: "narrator", content: "Outside, thunder rolls.", messageType: "event" },
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
  it("shows a fork button on persisted response turns when onForkFromTurn is provided", () => {
    renderPanel({ onForkFromTurn: vi.fn() });
    // Forkable: assistant (id 2) + narrator (id 3). Not: user (id 1), live (live-abc).
    expect(screen.getAllByRole("button", { name: /fork from here/i })).toHaveLength(2);
  });

  it("does not offer forking on the user's own line", () => {
    renderPanel({ onForkFromTurn: vi.fn() });
    // The user message bubble (role "You") must have no fork button — forking
    // there would leave a reply-less fork.
    const userBubble = screen.getByText("I open the door.").closest("article")!;
    expect(within(userBubble).queryByRole("button", { name: /fork from here/i })).not.toBeInTheDocument();
  });

  it("renders no fork buttons when onForkFromTurn is omitted", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: /fork from here/i })).not.toBeInTheDocument();
  });

  it("calls onForkFromTurn with the turn index of the clicked response", async () => {
    const onFork = vi.fn();
    renderPanel({ onForkFromTurn: onFork });
    // The assistant turn (id "2") owns the first fork button.
    const assistantBubble = screen.getByText("The hinges groan.").closest("article")!;
    await userEvent.click(within(assistantBubble).getByRole("button", { name: /fork from here/i }));
    expect(onFork).toHaveBeenCalledExactlyOnceWith(2);
  });

  it("shows a busy label on the forking turn and disables the buttons", () => {
    renderPanel({ onForkFromTurn: vi.fn(), forkingTurn: 2 });
    expect(screen.getByRole("button", { name: /forking/i })).toBeDisabled();
    // The other fork button (narrator, id 3) is disabled too while in flight.
    expect(screen.getByRole("button", { name: /fork from here/i })).toBeDisabled();
  });
});
