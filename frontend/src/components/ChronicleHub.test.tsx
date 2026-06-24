import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChronicleListItem } from "../types";
import { server } from "../test/server";
import { ChronicleHub } from "./ChronicleHub";

function makeChronicle(overrides: Partial<ChronicleListItem> = {}): ChronicleListItem {
  return {
    id: "orig-1",
    title: "The Original",
    status: "active",
    gm_enabled: false,
    turn_count: 12,
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:00Z",
    character_card_id: "cc-1",
    world_state_id: null,
    character_name: "Aria",
    world_name: "Shadowrealm",
    summary: null,
    suggestions_enabled: false,
    world_state_enabled: false,
    quests_enabled: false,
    dice_enabled: false,
    character_sheet_enabled: false,
    permadeath_enabled: false,
    parent_session_id: null,
    forked_at_turn: null,
    ...overrides,
  };
}

function ChroniclePageMarker() {
  const { id } = useParams();
  return <div data-testid="chronicle-page">chronicle {id}</div>;
}

function renderHub() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<ChronicleHub />} />
        <Route path="/chronicle/new" element={<div data-testid="new-chronicle">new chronicle</div>} />
        <Route path="/chronicle/:id" element={<ChroniclePageMarker />} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockSessions(sessions: ChronicleListItem[]) {
  server.use(http.get("/api/sessions", () => HttpResponse.json({ sessions })));
}

describe("ChronicleHub fork lineage", () => {
  it("shows a fork badge on forked chronicles and not on originals", async () => {
    server.use(
      http.get("/api/sessions", () =>
        HttpResponse.json({
          sessions: [
            makeChronicle({ id: "orig-1", title: "The Original" }),
            makeChronicle({
              id: "fork-9",
              title: "The Fork",
              parent_session_id: "orig-1",
              forked_at_turn: 5,
            }),
          ],
        }),
      ),
    );

    const { container } = renderHub();

    // The card <article> is itself role=button, so query the badge by its exact
    // aria-label to disambiguate from the card's (substring-matching) name.
    const badge = await screen.findByRole("button", {
      name: "Open parent chronicle (forked at turn 5)",
    });
    expect(badge).toBeInTheDocument();
    // Only the forked card carries a badge; the original has none.
    expect(container.querySelectorAll(".badge-fork")).toHaveLength(1);
  });

  it("navigates to the parent (not the fork) when the badge is clicked", async () => {
    server.use(
      http.get("/api/sessions", () =>
        HttpResponse.json({
          sessions: [
            makeChronicle({
              id: "fork-9",
              title: "The Fork",
              parent_session_id: "orig-1",
              forked_at_turn: 5,
            }),
          ],
        }),
      ),
    );

    renderHub();

    const badge = await screen.findByRole("button", {
      name: "Open parent chronicle (forked at turn 5)",
    });
    await userEvent.click(badge);

    // stopPropagation: clicking the badge opens the parent, not the fork's card.
    const page = await screen.findByTestId("chronicle-page");
    expect(page).toHaveTextContent("chronicle orig-1");
  });
});

describe("ChronicleHub list rendering", () => {
  it("shows a spinner while loading, then the chronicle list", async () => {
    mockSessions([makeChronicle({ id: "a", title: "First Tale" })]);
    renderHub();

    // Initial render: loading=true before the fetch resolves.
    expect(screen.getByText(/consulting the archive/i)).toBeInTheDocument();

    expect(await screen.findByText("First Tale")).toBeInTheDocument();
    expect(screen.queryByText(/consulting the archive/i)).not.toBeInTheDocument();
  });

  it("sorts chronicles by updated_at, most recent first", async () => {
    mockSessions([
      makeChronicle({ id: "old", title: "Older", updated_at: "2026-06-01T00:00:00Z" }),
      makeChronicle({ id: "new", title: "Newer", updated_at: "2026-06-18T00:00:00Z" }),
    ]);
    renderHub();

    await screen.findByText("Newer");
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(["Newer", "Older"]);
  });

  it("renders feature badges and the turn count", async () => {
    mockSessions([
      makeChronicle({
        id: "a",
        title: "Loaded",
        gm_enabled: true,
        world_state_enabled: true,
        quests_enabled: true,
        turn_count: 7,
      }),
    ]);
    renderHub();

    const card = (await screen.findByText("Loaded")).closest("article")!;
    expect(within(card).getByText("GM")).toBeInTheDocument();
    expect(within(card).getByText(/ledger/i)).toBeInTheDocument();
    expect(within(card).getByText(/quests/i)).toBeInTheDocument();
    expect(within(card).getByText("7 turns")).toBeInTheDocument();
  });

  it("navigates to the chronicle when a card is clicked", async () => {
    mockSessions([makeChronicle({ id: "go-here", title: "Open Me" })]);
    renderHub();

    await userEvent.click(await screen.findByText("Open Me"));
    expect(await screen.findByTestId("chronicle-page")).toHaveTextContent("chronicle go-here");
  });
});

describe("ChronicleHub empty + create", () => {
  it("shows the empty state and routes to new-chronicle creation", async () => {
    mockSessions([]);
    renderHub();

    expect(await screen.findByText(/the vault is empty/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /open new chronicle/i }));
    expect(await screen.findByTestId("new-chronicle")).toBeInTheDocument();
  });

  it("shows a header create button when chronicles exist", async () => {
    mockSessions([makeChronicle({ id: "a", title: "Existing" })]);
    renderHub();

    await screen.findByText("Existing");
    await userEvent.click(screen.getByRole("button", { name: /open new chronicle/i }));
    expect(await screen.findByTestId("new-chronicle")).toBeInTheDocument();
  });
});

describe("ChronicleHub delete flow", () => {
  afterEach(() => vi.restoreAllMocks());

  it("deletes a chronicle after confirmation and removes its card", async () => {
    let deleted = false;
    mockSessions([
      makeChronicle({ id: "keep", title: "Keep Me" }),
      makeChronicle({ id: "drop", title: "Drop Me" }),
    ]);
    server.use(
      http.delete("/api/session/drop", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderHub();
    const card = (await screen.findByText("Drop Me")).closest("article")!;
    await userEvent.click(within(card).getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(screen.queryByText("Drop Me")).not.toBeInTheDocument());
    expect(deleted).toBe(true);
    expect(screen.getByText("Keep Me")).toBeInTheDocument();
  });

  it("does not delete when the confirmation is declined", async () => {
    let called = false;
    mockSessions([makeChronicle({ id: "drop", title: "Drop Me" })]);
    server.use(
      http.delete("/api/session/drop", () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderHub();
    const card = (await screen.findByText("Drop Me")).closest("article")!;
    await userEvent.click(within(card).getByRole("button", { name: /delete/i }));

    expect(called).toBe(false);
    expect(screen.getByText("Drop Me")).toBeInTheDocument();
  });

  it("alerts and keeps the card when the delete request fails", async () => {
    mockSessions([makeChronicle({ id: "drop", title: "Drop Me" })]);
    server.use(
      http.delete("/api/session/drop", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    renderHub();
    const card = (await screen.findByText("Drop Me")).closest("article")!;
    await userEvent.click(within(card).getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith("boom"));
    expect(screen.getByText("Drop Me")).toBeInTheDocument();
  });
});

describe("ChronicleHub error handling", () => {
  it("shows an error banner and reloads on retry", async () => {
    let attempt = 0;
    server.use(
      http.get("/api/sessions", () => {
        attempt += 1;
        if (attempt === 1) return HttpResponse.json({ detail: "archive sealed" }, { status: 500 });
        return HttpResponse.json({ sessions: [makeChronicle({ id: "a", title: "Recovered" })] });
      }),
    );

    renderHub();
    expect(await screen.findByRole("alert")).toHaveTextContent("archive sealed");

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Recovered")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
