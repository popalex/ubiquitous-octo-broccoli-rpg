import type { Dispatch, SetStateAction } from "react";
import { attachSuggestionsToLatestReply, cleanSuggestions } from "./suggestions";
import { withUiSpan } from "./telemetry";
import type { ChatMessage, DiceRoll, GMEvent, QuestUpdateNotification, RetrievedMemory } from "./types";

/** Quest changes worth announcing as a narrator card (vs. status-bar only). */
const ANNOUNCED_QUEST_CHANGES = ["offered", "started", "escalated", "completed", "failed"];

function questAnnouncement(quest: QuestUpdateNotification): string {
  const detail = quest.detail ? ` — ${quest.detail}` : "";
  switch (quest.change) {
    case "offered":
      return `**A new thread beckons:** ${quest.title}${detail}`;
    case "started":
      return `**Quest taken up:** ${quest.title}${detail}`;
    case "escalated":
      return `**The world moves without you:** ${quest.title}${detail}`;
    case "completed":
      return `**Quest concluded:** ${quest.title}${detail}`;
    case "failed":
      return `**Quest failed:** ${quest.title}${detail}`;
    default:
      return `**Quest ${quest.change}:** ${quest.title}${detail}`;
  }
}

function handleQuestUpdate(
  quest: QuestUpdateNotification,
  setChatMessages: Dispatch<SetStateAction<ChatMessage[]>>,
  setStatusText: (v: string) => void,
): void {
  setStatusText(`Quest ${quest.change}: ${quest.title}`);
  if (!ANNOUNCED_QUEST_CHANGES.includes(quest.change)) return;
  setChatMessages((current) => [
    ...current,
    {
      id: crypto.randomUUID(),
      role: "narrator",
      content: questAnnouncement(quest),
      messageType: "quest",
    },
  ]);
}

// Attach suggested next-action chips from a live SSE frame to the most recent
// assistant/narrator message. Targeting lives in the shared helper so the
// chronicle-reload path attaches chips identically.
function attachSuggestions(
  suggestions: unknown,
  setChatMessages: Dispatch<SetStateAction<ChatMessage[]>>,
): void {
  const cleaned = cleanSuggestions(suggestions);
  if (cleaned.length === 0) return;
  setChatMessages((current) => attachSuggestionsToLatestReply(current, cleaned));
}

export type SendChatParams = {
  sessionId: string;
  chatInput: string;
  setChatInput: (v: string) => void;
  gmEnabled: boolean;
  currentLocation: string;
  timeOfDay: string;
  setChatMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setRetrievedMemories: Dispatch<SetStateAction<RetrievedMemory[]>>;
  setContinuityIssues: Dispatch<SetStateAction<string[]>>;
  setLastEvent: Dispatch<SetStateAction<GMEvent | null>>;
  setStatusText: (v: string) => void;
  setIsBusy: (v: boolean) => void;
  refreshMemory: (sessionId: string) => Promise<void>;
};

type StreamParams = SendChatParams & {
  currentInput: string;
  userMessage: ChatMessage;
};

export async function sendChat(params: SendChatParams): Promise<void> {
  const { sessionId, chatInput, setChatInput, gmEnabled, setStatusText, setIsBusy } = params;

  if (!sessionId) {
    setStatusText("Start a session first.");
    return;
  }
  if (!chatInput.trim()) {
    setStatusText("Write a message first.");
    return;
  }

  const currentInput = chatInput.trim();
  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: currentInput,
  };

  params.setChatMessages((current) => [...current, userMessage]);
  setChatInput("");
  setIsBusy(true);

  await withUiSpan(
    "ui.send_chat",
    { "rpg.session_id": sessionId, "rpg.gm_enabled": gmEnabled },
    () =>
      gmEnabled
        ? sendGMStream({ ...params, currentInput, userMessage })
        : sendStandardStream({ ...params, currentInput, userMessage }),
  );
}

/** Append streamed text to the message with ``messageId`` (no-op if it isn't
 * in the list yet — the GM reply bubble is added lazily on `character_reply`). */
function appendChunk(
  setChatMessages: Dispatch<SetStateAction<ChatMessage[]>>,
  messageId: string,
  content: string,
): void {
  setChatMessages((current) =>
    current.map((msg) => (msg.id === messageId ? { ...msg, content: msg.content + content } : msg)),
  );
}

type SSEEvent = Record<string, unknown>;
type SSEHandler = (event: SSEEvent) => void | Promise<void>;
/** Maps an SSE `type` to its handler; unknown types are ignored. */
type SSEHandlers = Record<string, SSEHandler>;

/** Open an SSE POST stream, throwing on a non-OK response. */
async function openStream(url: string, body: object): Promise<Response> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(response.statusText || "Stream request failed");
  return response;
}

/** Read an SSE body to completion, dispatching each parsed frame to its
 * handler. Handles the `data:` prefix, blank/keep-alive lines, malformed JSON
 * (skipped), and frames split across read boundaries. A throwing handler (e.g.
 * the `error` frame) propagates to the caller's try/catch for rollback. */
async function readSSEStream(response: Response, handlers: SSEHandlers): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Failed to get response reader");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const jsonStr = line.slice(6);
      if (!jsonStr.trim()) continue;

      let event: SSEEvent;
      try {
        event = JSON.parse(jsonStr) as SSEEvent;
      } catch {
        continue; // Skip malformed JSON lines
      }

      const handler = handlers[event.type as string];
      if (handler) await handler(event);
    }
  }
}

/** Frame handlers common to both stream paths (standard's events are a strict
 * subset of the GM path's). Each path spreads these and adds/overrides its own
 * `phase` / `done` (and, for GM, the pre-narration + event frames). */
function commonStreamHandlers({
  assistantMessageId,
  setChatMessages,
  setRetrievedMemories,
  setStatusText,
}: {
  assistantMessageId: string;
  setChatMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setRetrievedMemories: Dispatch<SetStateAction<RetrievedMemory[]>>;
  setStatusText: (v: string) => void;
}): SSEHandlers {
  return {
    chunk: (event) => appendChunk(setChatMessages, assistantMessageId, event.content as string),
    memories: (event) => setRetrievedMemories(event.memories as RetrievedMemory[]),
    quest_update: (event) =>
      handleQuestUpdate(event.quest as QuestUpdateNotification, setChatMessages, setStatusText),
    suggestions: (event) => attachSuggestions(event.suggestions as string[], setChatMessages),
    error: (event) => {
      throw new Error((event.error as string) || "Stream failed.");
    },
  };
}

async function sendGMStream({
  sessionId,
  currentInput,
  userMessage,
  currentLocation,
  timeOfDay,
  setChatMessages,
  setRetrievedMemories,
  setContinuityIssues,
  setLastEvent,
  setStatusText,
  setIsBusy,
  refreshMemory,
  setChatInput,
}: StreamParams): Promise<void> {
  const preNarrationId = crypto.randomUUID();
  const assistantMessageId = crypto.randomUUID();

  setChatMessages((current) => [
    ...current,
    { id: preNarrationId, role: "narrator", content: "", messageType: "pre_narration" },
  ]);
  setStatusText("The Game Master weaves the tale...");

  let hasAddedAssistant = false;
  let hasPreNarration = false;

  try {
    const response = await openStream("/api/gm/chat/stream", {
      session_id: sessionId,
      user_message: currentInput,
      gm_mode: true,
      location: currentLocation || null,
      time_of_day: timeOfDay || null,
    });

    await readSSEStream(response, {
      ...commonStreamHandlers({ assistantMessageId, setChatMessages, setRetrievedMemories, setStatusText }),
      phase: (event) => {
        if (event.phase === "character_reply") {
          if (!hasAddedAssistant) {
            hasAddedAssistant = true;
            setChatMessages((current) => [
              ...current,
              { id: assistantMessageId, role: "assistant", content: "", messageType: "chat" },
            ]);
            setStatusText("Character responds...");
          }
        } else if (event.phase === "summarizing") {
          setStatusText("Updating memory scrolls…");
        }
      },
      pre_narration_chunk: (event) => {
        hasPreNarration = true;
        appendChunk(setChatMessages, preNarrationId, event.content as string);
      },
      pre_narration_error: () => {
        // The GM narration broke mid-stream. Discard the half-written bubble
        // (the backend discards it too) rather than leaving a dangling fragment.
        hasPreNarration = false;
        setChatMessages((current) => current.filter((msg) => msg.id !== preNarrationId));
        setStatusText("The Game Master faltered; continuing without narration…");
      },
      roll: (event) => {
        const roll = event.roll as DiceRoll;
        const verdict = roll.outcome.replace("_", " ");
        setChatMessages((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            role: "narrator",
            content: `Skill check — ${roll.skill_label} vs DC ${roll.dc}: rolled ${roll.die} (${verdict})`,
            messageType: "roll",
            roll,
          },
        ]);
        setStatusText(`Skill check: ${roll.skill_label} — ${verdict}`);
      },
      event: (event) => {
        const gmEvent = event.event as GMEvent;
        setLastEvent(gmEvent);
        setChatMessages((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            role: "narrator",
            content: gmEvent.description,
            messageType: "event",
          },
        ]);
        setStatusText(`Event triggered: ${gmEvent.event_type}`);
      },
      done: async () => {
        // Best-effort: a failed refetch must not wipe the finished reply.
        await refreshMemory(sessionId).catch(() => {});
        if (!hasPreNarration) {
          setChatMessages((current) => current.filter((msg) => msg.id !== preNarrationId));
        }
      },
    });

    setContinuityIssues([]);
    setStatusText("The tale unfolds...");
  } catch (error) {
    setChatMessages((current) =>
      current.filter(
        (item) =>
          item.id !== userMessage.id &&
          item.id !== preNarrationId &&
          item.id !== assistantMessageId
      )
    );
    setChatInput(currentInput);
    setStatusText(error instanceof Error ? error.message : "GM chat request failed.");
  } finally {
    setIsBusy(false);
  }
}

async function sendStandardStream({
  sessionId,
  currentInput,
  userMessage,
  setChatMessages,
  setRetrievedMemories,
  setContinuityIssues,
  setStatusText,
  setIsBusy,
  refreshMemory,
  setChatInput,
}: StreamParams): Promise<void> {
  const assistantMessageId = crypto.randomUUID();

  setChatMessages((current) => [
    ...current,
    { id: assistantMessageId, role: "assistant", content: "" },
  ]);
  setStatusText("Generating in-character reply...");

  try {
    const response = await openStream("/api/chat/stream", {
      session_id: sessionId,
      user_message: currentInput,
    });

    await readSSEStream(response, {
      ...commonStreamHandlers({ assistantMessageId, setChatMessages, setRetrievedMemories, setStatusText }),
      phase: (event) => {
        if (event.phase === "summarizing") setStatusText("Updating memory scrolls…");
      },
      done: async () => {
        // Best-effort: a failed refetch must not wipe the finished reply.
        await refreshMemory(sessionId).catch(() => {});
      },
    });

    setContinuityIssues([]);
    setStatusText("Reply generated.");
  } catch (error) {
    setChatMessages((current) =>
      current.filter(
        (item) => item.id !== userMessage.id && item.id !== assistantMessageId
      )
    );
    setChatInput(currentInput);
    setStatusText(error instanceof Error ? error.message : "Chat request failed.");
  } finally {
    setIsBusy(false);
  }
}
