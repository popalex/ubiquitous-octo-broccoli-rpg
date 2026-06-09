import { afterEach, describe, expect, it, vi } from "vitest";

import { api, listToText, textToList } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown>; text?: () => Promise<string> }) {
  const fetchMock = vi.fn().mockResolvedValue(response as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("api()", () => {
  it("prefixes /api and returns parsed JSON on success", async () => {
    const fetchMock = mockFetch({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: () => Promise.resolve({ hello: "world" }),
    });

    const result = await api<{ hello: string }>("/health");

    expect(result).toEqual({ hello: "world" });
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.objectContaining({
      headers: expect.objectContaining({ "Content-Type": "application/json" }),
    }));
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch({ ok: true, status: 204, headers: new Headers() });

    const result = await api<undefined>("/session/x", { method: "DELETE" });

    expect(result).toBeUndefined();
  });

  it("throws with the body.detail message on error responses", async () => {
    mockFetch({
      ok: false,
      status: 404,
      statusText: "Not Found",
      headers: new Headers(),
      json: () => Promise.resolve({ detail: "Session not found." }),
    });

    await expect(api("/session/missing")).rejects.toThrow("Session not found.");
  });
});

describe("text/list helpers", () => {
  it("round-trips list <-> text, trimming and dropping blanks", () => {
    expect(textToList("a\n  b  \n\n c ")).toEqual(["a", "b", "c"]);
    expect(listToText(["a", "b"])).toBe("a\nb");
  });
});
