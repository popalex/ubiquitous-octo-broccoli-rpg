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

describe("ChatPanel suggestion chips", () => {
  const withSuggestions: ChatMessage[] = [
    { id: "1", role: "user", content: "I open the door." },
    // An earlier reply that also carries suggestions — must NOT render them.
    { id: "2", role: "assistant", content: "The hinges groan.", suggestions: ["Old chip"] },
    { id: "live-abc", role: "assistant", content: "A draft stirs.", suggestions: ["Light a torch", "Draw your blade"] },
  ];

  it("renders chips only on the latest reply and sends the chip text on click", async () => {
    const onSendChat = vi.fn();
    renderPanel({ chatMessages: withSuggestions, onSendChat });

    // Only the latest message's chips show — the stale "Old chip" is hidden.
    expect(screen.queryByRole("button", { name: "Old chip" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Light a torch" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Draw your blade" }));
    expect(onSendChat).toHaveBeenCalledExactlyOnceWith("Draw your blade");
  });

  it("hides chips while a turn is in flight", () => {
    renderPanel({ chatMessages: withSuggestions, isBusy: true });
    expect(screen.queryByRole("button", { name: "Light a torch" })).not.toBeInTheDocument();
  });

  it("leaves the composer usable alongside chips", () => {
    renderPanel({ chatMessages: withSuggestions });
    expect(screen.getByRole("textbox", { name: /write your response/i })).toBeEnabled();
  });
});

describe("ChatPanel message rendering", () => {
  it("renders each message with content and a role label", () => {
    renderPanel();
    expect(screen.getByText("I open the door.")).toBeInTheDocument();
    expect(screen.getByText("The hinges groan.")).toBeInTheDocument();
    // User lines are labelled "You"; the assistant uses the character name.
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getAllByText("Aria").length).toBeGreaterThan(0);
    // The narrator turn is labelled "Game Master".
    expect(screen.getByText("Game Master")).toBeInTheDocument();
  });

  it("tags each message with role + type classes", () => {
    renderPanel();
    const narrator = screen.getByText("Outside, thunder rolls.").closest("article")!;
    expect(narrator).toHaveClass("message-narrator");
    expect(narrator).toHaveClass("message-type-event");
  });

  it("shows the empty state when there are no messages", () => {
    renderPanel({ chatMessages: [] });
    expect(screen.getByText(/the pages await your tale/i)).toBeInTheDocument();
    expect(screen.queryByText("I open the door.")).not.toBeInTheDocument();
  });

  it("renders the status text in the composer", () => {
    renderPanel({ statusText: "weaving the tale…" });
    expect(screen.getByText("weaving the tale…")).toBeInTheDocument();
  });
});

describe("ChatPanel composer", () => {
  it("calls onSendChat and forwards typed input", async () => {
    const onSendChat = vi.fn();
    const setChatInput = vi.fn();
    renderPanel({ onSendChat, setChatInput });

    await userEvent.type(screen.getByRole("textbox", { name: /write your response/i }), "hi");
    expect(setChatInput).toHaveBeenCalled();

    // Send with no explicit argument — composes from the controlled input.
    await userEvent.click(screen.getByRole("button", { name: /send turn/i }));
    expect(onSendChat).toHaveBeenCalledExactlyOnceWith();
  });

  it("disables the send button while busy and shows a weaving label", () => {
    renderPanel({ isBusy: true });
    expect(screen.getByRole("button", { name: /weaving/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /send turn/i })).not.toBeInTheDocument();
  });

  it("disables the send button when there is no active session", () => {
    renderPanel({ sessionId: "" });
    expect(screen.getByRole("button", { name: /send turn/i })).toBeDisabled();
  });
});
