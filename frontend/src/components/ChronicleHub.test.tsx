import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { describe, expect, it } from "vitest";

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
        <Route path="/chronicle/:id" element={<ChroniclePageMarker />} />
      </Routes>
    </MemoryRouter>,
  );
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
