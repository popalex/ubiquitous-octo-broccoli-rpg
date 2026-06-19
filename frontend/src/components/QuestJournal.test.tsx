import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Quest, SessionQuests } from "../types";
import { renderWithClient } from "../test/renderWithClient";
import { server } from "../test/server";
import { QuestJournal } from "./QuestJournal";

function makeQuest(overrides: Partial<Quest> = {}): Quest {
  return {
    id: "q1",
    slug: "the-missing-heir",
    title: "The Missing Heir",
    quest_type: "mystery",
    description: "Find out who took the heir.",
    stakes: null,
    status: "active",
    origin: "gm",
    stages: [],
    resolution: null,
    created_turn: 1,
    accepted_turn: 1,
    last_progress_turn: 2,
    resolved_turn: null,
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:00Z",
    ...overrides,
  };
}

function makeQuests(quests: Quest[]): SessionQuests {
  return { session_id: "sess-1", quests };
}

describe("QuestJournal", () => {
  it("shows the empty state when there are no quests", () => {
    renderWithClient(<QuestJournal sessionId="sess-1" quests={makeQuests([])} />);
    expect(screen.getByText(/no arcs bind you yet/i)).toBeInTheDocument();
  });

  it("shows the empty state when quests is null", () => {
    renderWithClient(<QuestJournal sessionId="sess-1" quests={null} />);
    expect(screen.getByText(/no arcs bind you yet/i)).toBeInTheDocument();
  });

  it("sorts quests into Active, Whispers & Offers, and Concluded sections", () => {
    const quests = makeQuests([
      makeQuest({ id: "a", title: "Active One", status: "active" }),
      makeQuest({ id: "e", title: "Escalating One", status: "escalating" }),
      makeQuest({ id: "r", title: "Rumored One", status: "rumored" }),
      makeQuest({ id: "o", title: "Offered One", status: "offered" }),
      makeQuest({ id: "c", title: "Completed One", status: "completed" }),
    ]);
    renderWithClient(<QuestJournal sessionId="sess-1" quests={quests} />);

    expect(screen.getByRole("heading", { name: /active arcs/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /whispers & offers/i })).toBeInTheDocument();
    // Active section holds active + escalating.
    expect(screen.getByText("Active One")).toBeInTheDocument();
    expect(screen.getByText("Escalating One")).toBeInTheDocument();
    // Offers section holds rumored + offered.
    expect(screen.getByText("Rumored One")).toBeInTheDocument();
    expect(screen.getByText("Offered One")).toBeInTheDocument();
    // Concluded is a collapsible details with a count.
    expect(screen.getByText(/concluded \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText("Completed One")).toBeInTheDocument();
  });

  it("hides a section when it has no quests", () => {
    renderWithClient(
      <QuestJournal
        sessionId="sess-1"
        quests={makeQuests([makeQuest({ status: "active" })])}
      />,
    );
    expect(screen.getByRole("heading", { name: /active arcs/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /whispers & offers/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/concluded \(/i)).not.toBeInTheDocument();
  });

  it("flags an escalating quest with an 'escalating' label", () => {
    renderWithClient(
      <QuestJournal
        sessionId="sess-1"
        quests={makeQuests([makeQuest({ id: "e", title: "Doom", status: "escalating" })])}
      />,
    );
    const card = screen.getByText("Doom").closest(".issue-card")!;
    expect(card).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("escalating")).toBeInTheDocument();
  });

  it("renders stakes and stages with done/not-done state", () => {
    const quest = makeQuest({
      stakes: "The kingdom falls",
      stages: [
        { id: "s1", description: "Search the docks", done: true },
        { id: "s2", description: "Question the captain", done: false },
      ],
    });
    renderWithClient(<QuestJournal sessionId="sess-1" quests={makeQuests([quest])} />);

    expect(screen.getByText(/at stake: the kingdom falls/i)).toBeInTheDocument();
    const doneStage = screen.getByText("Search the docks").closest("li")!;
    const openStage = screen.getByText("Question the captain").closest("li")!;
    expect(doneStage).toHaveClass("muted");
    expect(openStage).not.toHaveClass("muted");
  });

  it("renders a concluded quest's resolution text", () => {
    const quest = makeQuest({
      title: "The Bargain",
      status: "resolved",
      resolution: "The pact was sealed in blood.",
    });
    renderWithClient(<QuestJournal sessionId="sess-1" quests={makeQuests([quest])} />);
    expect(screen.getByText(/the pact was sealed in blood/i)).toBeInTheDocument();
  });

  it("offers Abandon only on active arcs", () => {
    const quests = makeQuests([
      makeQuest({ id: "a", title: "Active One", status: "active" }),
      makeQuest({ id: "o", title: "Offered One", status: "offered" }),
      makeQuest({ id: "c", title: "Done One", status: "completed" }),
    ]);
    renderWithClient(<QuestJournal sessionId="sess-1" quests={quests} />);

    // Exactly one Abandon button — on the active card.
    const buttons = screen.getAllByRole("button", { name: /abandon/i });
    expect(buttons).toHaveLength(1);
    const activeCard = screen.getByText("Active One").closest(".memory-card")!;
    expect(within(activeCard as HTMLElement).getByRole("button", { name: /abandon/i })).toBeInTheDocument();
  });

  it("PATCHes the quest to abandoned when Abandon is clicked", async () => {
    let captured: { id: string; body: unknown } | null = null;
    server.use(
      http.patch("/api/session/sess-1/quests/:questId", async ({ params, request }) => {
        captured = { id: params.questId as string, body: await request.json() };
        return HttpResponse.json(makeQuest({ status: "abandoned" }));
      }),
    );

    renderWithClient(
      <QuestJournal
        sessionId="sess-1"
        quests={makeQuests([makeQuest({ id: "q1", status: "active" })])}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /abandon/i }));

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured!.id).toBe("q1");
    expect(captured!.body).toEqual({ status: "abandoned" });
  });
});
