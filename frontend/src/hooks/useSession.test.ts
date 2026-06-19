import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { createWrapper } from "../test/renderWithClient";
import { server } from "../test/server";
import {
  sessionKeys,
  useRefreshMemory,
  useSessionDetail,
  useSessionQuests,
  useSessionSuggestions,
} from "./useSession";

describe("sessionKeys", () => {
  it("namespaces every read under a stable, session-scoped key", () => {
    expect(sessionKeys.detail("s1")).toEqual(["session", "s1", "detail"]);
    expect(sessionKeys.turns("s1")).toEqual(["session", "s1", "turns"]);
    expect(sessionKeys.memory("s1")).toEqual(["session", "s1", "memory"]);
    expect(sessionKeys.worldState("s1")).toEqual(["session", "s1", "world-state"]);
    expect(sessionKeys.quests("s1")).toEqual(["session", "s1", "quests"]);
    expect(sessionKeys.suggestions("s1")).toEqual(["session", "s1", "suggestions"]);
  });
});

describe("useSessionDetail", () => {
  it("fetches session detail through the api wrapper", async () => {
    server.use(
      http.get("/api/session/s1", () => HttpResponse.json({ id: "s1", title: "My Tale" })),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useSessionDetail("s1"), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toMatchObject({ id: "s1", title: "My Tale" });
  });

  it("stays idle when given no session id", () => {
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useSessionDetail(""), { wrapper: Wrapper });
    // enabled: !!sessionId — disabled query never fetches: it parks in a
    // pending status with an idle fetchStatus rather than loading data.
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.isPending).toBe(true);
  });
});

describe("useSessionSuggestions", () => {
  it("does not fetch when disabled, even with a valid session id", () => {
    const spy = vi.fn();
    server.use(
      http.get("/api/session/s1/suggestions", () => {
        spy();
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useSessionSuggestions("s1", false), { wrapper: Wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches when enabled", async () => {
    server.use(
      http.get("/api/session/s1/suggestions", () =>
        HttpResponse.json({ suggestions: ["Run", "Hide"] }),
      ),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useSessionSuggestions("s1", true), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.suggestions).toEqual(["Run", "Hide"]);
  });
});

describe("useSessionQuests", () => {
  it("surfaces an error without retrying (retry: false)", async () => {
    server.use(
      http.get("/api/session/s1/quests", () => HttpResponse.json({ detail: "off" }, { status: 404 })),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useSessionQuests("s1"), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Error);
  });
});

describe("useRefreshMemory", () => {
  it("invalidates memory, world-state, and quests — but not detail/turns", async () => {
    const { client, Wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useRefreshMemory(), { wrapper: Wrapper });
    await result.current("s1");

    const keys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(sessionKeys.memory("s1"));
    expect(keys).toContainEqual(sessionKeys.worldState("s1"));
    expect(keys).toContainEqual(sessionKeys.quests("s1"));
    expect(keys).not.toContainEqual(sessionKeys.detail("s1"));
    expect(keys).not.toContainEqual(sessionKeys.turns("s1"));
  });

  it("returns a stable callback across re-renders", () => {
    const { Wrapper } = createWrapper();
    const { result, rerender } = renderHook(() => useRefreshMemory(), { wrapper: Wrapper });
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
