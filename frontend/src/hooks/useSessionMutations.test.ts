import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { createWrapper } from "../test/renderWithClient";
import { server } from "../test/server";
import { useForkSession, useStartSession } from "./useSessionMutations";

describe("useStartSession", () => {
  it("POSTs the init payload and returns the new session", async () => {
    let body: unknown = null;
    server.use(
      http.post("/api/session/init", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ session_id: "new-1", turn_count: 0 });
      }),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useStartSession(), { wrapper: Wrapper });

    result.current.mutate({
      character_card_id: "cc-1",
      world_state_id: "ws-1",
      title: "A New Tale",
      gm_enabled: true,
      suggestions_enabled: null,
      current_location: null,
      time_of_day: null,
      world_state_enabled: null,
      quests_enabled: null,
      dice_enabled: null,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.session_id).toBe("new-1");
    expect(body).toMatchObject({ character_card_id: "cc-1", title: "A New Tale", gm_enabled: true });
  });
});

describe("useForkSession", () => {
  it("forks at a specific turn, sending at_turn in the body", async () => {
    let body: unknown = null;
    server.use(
      http.post("/api/session/s1/fork", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "fork-1", parent_session_id: "s1", forked_at_turn: 5 });
      }),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useForkSession(), { wrapper: Wrapper });

    result.current.mutate({ sessionId: "s1", atTurn: 5 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("fork-1");
    expect(body).toEqual({ at_turn: 5, title: null });
  });

  it("forks the whole chronicle (at_turn: null) when atTurn is omitted", async () => {
    let body: unknown = null;
    server.use(
      http.post("/api/session/s1/fork", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "fork-2" });
      }),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useForkSession(), { wrapper: Wrapper });

    result.current.mutate({ sessionId: "s1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(body).toEqual({ at_turn: null, title: null });
  });

  it("surfaces a server error to the mutation", async () => {
    server.use(
      http.post("/api/session/s1/fork", () =>
        HttpResponse.json({ detail: "cannot fork" }, { status: 400 }),
      ),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useForkSession(), { wrapper: Wrapper });

    result.current.mutate({ sessionId: "s1", atTurn: 2 });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ message: "cannot fork" });
  });
});
