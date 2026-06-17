import { afterEach, describe, expect, it, vi } from "vitest";

import { sendChat, type SendChatParams } from "./chat";
import type { ChatMessage, GMEvent, RetrievedMemory } from "./types";

// Keep the test focused on stream handling — no OTel spans.
vi.mock("./telemetry", () => ({
  withUiSpan: <T,>(_name: string, _attrs: Record<string, unknown>, fn: () => Promise<T>) => fn(),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const last = (log: string[]) => log[log.length - 1];

function sseFrame(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

/** Fake response body whose reader yields exactly the given chunks, so tests
 * control read boundaries. A chunk may hold several frames or half a frame. */
function streamBody(chunks: string[], { failAfter }: { failAfter?: number } = {}) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    getReader: () => ({
      read: async () => {
        if (failAfter !== undefined && i >= failAfter) {
          throw new Error("network dropped");
        }
        if (i < chunks.length) {
          return { done: false as const, value: encoder.encode(chunks[i++]) };
        }
        return { done: true as const, value: undefined };
      },
    }),
  };
}

function mockFetchStream(
  chunks: string[],
  options: { ok?: boolean; statusText?: string; failAfter?: number } = {},
) {
  const { ok = true, statusText = "", failAfter } = options;
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    statusText,
    body: streamBody(chunks, { failAfter }),
  } as unknown as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Minimal stand-in for the React state sendChat drives. */
function createHarness(overrides: Partial<SendChatParams> = {}) {
  const state = {
    messages: [] as ChatMessage[],
    memories: [] as RetrievedMemory[],
    continuityIssues: null as string[] | null,
    lastEvent: null as GMEvent | null,
    statusLog: [] as string[],
    busyLog: [] as boolean[],
    chatInput: "Hello there",
  };
  const refreshMemory = vi.fn().mockResolvedValue(undefined);
  const params: SendChatParams = {
    sessionId: "sess-1",
    chatInput: state.chatInput,
    setChatInput: (v) => {
      state.chatInput = v;
    },
    gmEnabled: false,
    currentLocation: "",
    timeOfDay: "",
    setChatMessages: (update) => {
      state.messages = typeof update === "function" ? update(state.messages) : update;
    },
    setRetrievedMemories: (update) => {
      state.memories = typeof update === "function" ? update(state.memories) : update;
    },
    setContinuityIssues: (update) => {
      state.continuityIssues =
        typeof update === "function" ? update(state.continuityIssues ?? []) : update;
    },
    setLastEvent: (update) => {
      state.lastEvent = typeof update === "function" ? update(state.lastEvent) : update;
    },
    setStatusText: (v) => {
      state.statusLog.push(v);
    },
    setIsBusy: (v) => {
      state.busyLog.push(v);
    },
    refreshMemory,
    ...overrides,
  };
  return { params, state, refreshMemory };
}

const MEMORY: RetrievedMemory = {
  id: "m1",
  kind: "fact",
  content: "The hero has a magic sword.",
  weighted_score: 0.9,
  semantic_score: 0.8,
  recency_score: 0.7,
  importance: 0.6,
};

describe("sendChat — standard stream", () => {
  it("accumulates chunks into the assistant reply and finishes cleanly", async () => {
    const fetchMock = mockFetchStream([
      sseFrame({ type: "memories", memories: [MEMORY] }),
      sseFrame({ type: "chunk", content: "Well " }),
      sseFrame({ type: "chunk", content: "met!" }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state, refreshMemory } = createHarness();

    await sendChat(params);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chat/stream",
      expect.objectContaining({ method: "POST" }),
    );
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({ role: "user", content: "Hello there" });
    expect(state.messages[1]).toMatchObject({ role: "assistant", content: "Well met!" });
    expect(state.memories).toEqual([MEMORY]);
    expect(refreshMemory).toHaveBeenCalledWith("sess-1");
    expect(state.chatInput).toBe(""); // cleared on send, not restored
    expect(state.busyLog).toEqual([true, false]);
    expect(last(state.statusLog)).toBe("Reply generated.");
  });

  it("handles frames split across read boundaries and bundled in one read", async () => {
    const frameA = sseFrame({ type: "chunk", content: "alpha " });
    const frameB = sseFrame({ type: "chunk", content: "beta " });
    const frameC = sseFrame({ type: "chunk", content: "gamma" });
    const done = sseFrame({ type: "done", session_id: "sess-1" });
    mockFetchStream([
      // half a frame, then the rest plus two more frames in a single read
      frameA.slice(0, 12),
      frameA.slice(12) + frameB + frameC.slice(0, 5),
      frameC.slice(5) + done,
    ]);
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages[1].content).toBe("alpha beta gamma");
  });

  it("skips malformed JSON frames without killing the stream", async () => {
    mockFetchStream([
      sseFrame({ type: "chunk", content: "first " }),
      "data: {definitely not json}\n\n",
      sseFrame({ type: "chunk", content: "second" }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages[1].content).toBe("first second");
    expect(state.busyLog).toEqual([true, false]);
  });

  it("announces quest updates as narrator cards", async () => {
    mockFetchStream([
      sseFrame({ type: "chunk", content: "On it." }),
      sseFrame({
        type: "quest_update",
        quest: { quest_id: "q1", slug: "find-her", title: "Find Her", status: "active", change: "started", detail: "A promise made" },
      }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state } = createHarness();

    await sendChat(params);

    const questCard = state.messages.find((m) => m.messageType === "quest");
    expect(questCard).toMatchObject({ role: "narrator" });
    expect(questCard?.content).toContain("Find Her");
    expect(state.statusLog).toContain("Quest started: Find Her");
  });

  it("attaches a suggestions frame to the assistant reply", async () => {
    mockFetchStream([
      sseFrame({ type: "chunk", content: "What now?" }),
      sseFrame({ type: "suggestions", suggestions: ["Search the desk", "Leave quietly"] }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages[1]).toMatchObject({ role: "assistant" });
    expect(state.messages[1].suggestions).toEqual(["Search the desk", "Leave quietly"]);
  });

  it("ignores an empty/malformed suggestions frame without killing the stream", async () => {
    mockFetchStream([
      sseFrame({ type: "chunk", content: "Onward." }),
      sseFrame({ type: "suggestions", suggestions: ["", "   ", 42] }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages[1].content).toBe("Onward.");
    expect(state.messages[1].suggestions).toBeUndefined();
    expect(state.busyLog).toEqual([true, false]);
  });

  it("rolls back the user message and restores input on an error frame", async () => {
    mockFetchStream([
      sseFrame({ type: "chunk", content: "partial" }),
      sseFrame({ type: "error", error: "model exploded" }),
    ]);
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages).toEqual([]);
    expect(state.chatInput).toBe("Hello there");
    expect(last(state.statusLog)).toBe("model exploded");
    expect(state.busyLog).toEqual([true, false]);
  });

  it("rolls back cleanly when the connection drops mid-stream", async () => {
    mockFetchStream([sseFrame({ type: "chunk", content: "partial" })], { failAfter: 1 });
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages).toEqual([]);
    expect(state.chatInput).toBe("Hello there");
    expect(last(state.statusLog)).toBe("network dropped");
    expect(state.busyLog).toEqual([true, false]);
  });

  it("keeps the finished reply when the post-stream memory refetch fails", async () => {
    mockFetchStream([
      sseFrame({ type: "chunk", content: "The tale ends." }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state } = createHarness({
      refreshMemory: vi.fn().mockRejectedValue(new Error("refetch failed")),
    });

    await sendChat(params);

    expect(state.messages[1]).toMatchObject({ role: "assistant", content: "The tale ends." });
    expect(last(state.statusLog)).toBe("Reply generated.");
    expect(state.busyLog).toEqual([true, false]);
  });

  it("rejects a non-OK response without leaving a stuck user message", async () => {
    mockFetchStream([], { ok: false, statusText: "Service Unavailable" });
    const { params, state } = createHarness();

    await sendChat(params);

    expect(state.messages).toEqual([]);
    expect(last(state.statusLog)).toBe("Service Unavailable");
  });

  it("refuses to send without a session or message", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const noSession = createHarness({ sessionId: "" });
    await sendChat(noSession.params);
    expect(last(noSession.state.statusLog)).toBe("Start a session first.");

    const noMessage = createHarness({ chatInput: "   " });
    await sendChat(noMessage.params);
    expect(last(noMessage.state.statusLog)).toBe("Write a message first.");

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("sendChat — GM stream", () => {
  const gmOverrides: Partial<SendChatParams> = {
    gmEnabled: true,
    currentLocation: "tavern",
    timeOfDay: "dusk",
  };

  it("streams pre-narration, character reply, and a GM event in order", async () => {
    const gmEvent: GMEvent = {
      event_type: "ambush",
      urgency: "immediate",
      description: "Bandits burst through the door.",
      npcs_involved: ["bandit"],
    };
    const fetchMock = mockFetchStream([
      sseFrame({ type: "memories", memories: [MEMORY] }),
      sseFrame({ type: "phase", phase: "pre_narration" }),
      sseFrame({ type: "pre_narration_chunk", content: "The room " }),
      sseFrame({ type: "pre_narration_chunk", content: "falls silent." }),
      sseFrame({ type: "phase", phase: "character_reply" }),
      sseFrame({ type: "chunk", content: "I draw " }),
      sseFrame({ type: "chunk", content: "my blade." }),
      sseFrame({ type: "event", event: gmEvent }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state, refreshMemory } = createHarness(gmOverrides);

    await sendChat(params);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/gm/chat/stream",
      expect.objectContaining({
        body: JSON.stringify({
          session_id: "sess-1",
          user_message: "Hello there",
          gm_mode: true,
          location: "tavern",
          time_of_day: "dusk",
        }),
      }),
    );
    // user message, pre-narration, assistant reply, event card
    expect(state.messages.map((m) => m.role)).toEqual(["user", "narrator", "assistant", "narrator"]);
    expect(state.messages[1]).toMatchObject({
      messageType: "pre_narration",
      content: "The room falls silent.",
    });
    expect(state.messages[2]).toMatchObject({ role: "assistant", content: "I draw my blade." });
    expect(state.messages[3]).toMatchObject({
      messageType: "event",
      content: "Bandits burst through the door.",
    });
    expect(state.lastEvent).toEqual(gmEvent);
    expect(state.memories).toEqual([MEMORY]);
    expect(refreshMemory).toHaveBeenCalledWith("sess-1");
    expect(state.busyLog).toEqual([true, false]);
  });

  it("drops the empty pre-narration placeholder when none was streamed", async () => {
    mockFetchStream([
      sseFrame({ type: "phase", phase: "character_reply" }),
      sseFrame({ type: "chunk", content: "Straight to it." }),
      sseFrame({ type: "done", session_id: "sess-1" }),
    ]);
    const { params, state } = createHarness(gmOverrides);

    await sendChat(params);

    expect(state.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(state.messages.some((m) => m.messageType === "pre_narration")).toBe(false);
  });

  it("rolls back user, pre-narration, and assistant messages on an error frame", async () => {
    mockFetchStream([
      sseFrame({ type: "pre_narration_chunk", content: "The room " }),
      sseFrame({ type: "phase", phase: "character_reply" }),
      sseFrame({ type: "chunk", content: "partial" }),
      sseFrame({ type: "error", error: "gm collapsed" }),
    ]);
    const { params, state } = createHarness(gmOverrides);

    await sendChat(params);

    expect(state.messages).toEqual([]);
    expect(state.chatInput).toBe("Hello there");
    expect(last(state.statusLog)).toBe("gm collapsed");
    expect(state.busyLog).toEqual([true, false]);
  });
});
