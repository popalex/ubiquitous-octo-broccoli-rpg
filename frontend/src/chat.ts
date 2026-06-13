import type { Dispatch, SetStateAction } from "react";
import { withUiSpan } from "./telemetry";
import type { ChatMessage, GMEvent, QuestUpdateNotification, RetrievedMemory } from "./types";

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

  try {
    const response = await fetch("/api/gm/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        user_message: currentInput,
        gm_mode: true,
        location: currentLocation || null,
        time_of_day: timeOfDay || null,
      }),
    });

    if (!response.ok) throw new Error(response.statusText || "Stream request failed");

    const reader = response.body?.getReader();
    if (!reader) throw new Error("Failed to get response reader");

    const decoder = new TextDecoder();
    let buffer = "";
    let hasAddedAssistant = false;
    let hasPreNarration = false;

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

        let event: Record<string, unknown>;
        try {
          event = JSON.parse(jsonStr) as Record<string, unknown>;
        } catch {
          continue; // Skip malformed JSON lines
        }

        if (event.type === "phase" && event.phase === "character_reply") {
          if (!hasAddedAssistant) {
            hasAddedAssistant = true;
            setChatMessages((current) => [
              ...current,
              { id: assistantMessageId, role: "assistant", content: "", messageType: "chat" },
            ]);
            setStatusText("Character responds...");
          }
        } else if (event.type === "phase" && event.phase === "summarizing") {
          setStatusText("Updating memory scrolls…");
        } else if (event.type === "pre_narration_chunk") {
          hasPreNarration = true;
          setChatMessages((current) =>
            current.map((msg) =>
              msg.id === preNarrationId
                ? { ...msg, content: msg.content + (event.content as string) }
                : msg
            )
          );
        } else if (event.type === "pre_narration_error") {
          // The GM narration broke mid-stream. Discard the half-written bubble
          // (the backend discards it too) rather than leaving a dangling fragment.
          hasPreNarration = false;
          setChatMessages((current) => current.filter((msg) => msg.id !== preNarrationId));
          setStatusText("The Game Master faltered; continuing without narration…");
        } else if (event.type === "chunk") {
          setChatMessages((current) =>
            current.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: msg.content + (event.content as string) }
                : msg
            )
          );
        } else if (event.type === "memories") {
          setRetrievedMemories(event.memories as RetrievedMemory[]);
        } else if (event.type === "event") {
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
        } else if (event.type === "quest_update") {
          handleQuestUpdate(event.quest as QuestUpdateNotification, setChatMessages, setStatusText);
        } else if (event.type === "error") {
          throw new Error((event.error as string) || "Stream failed.");
        } else if (event.type === "done") {
          // Best-effort: a failed refetch must not wipe the finished reply.
          await refreshMemory(sessionId).catch(() => {});
          if (!hasPreNarration) {
            setChatMessages((current) => current.filter((msg) => msg.id !== preNarrationId));
          }
        }
      }
    }

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
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        user_message: currentInput,
      }),
    });

    if (!response.ok) throw new Error(response.statusText || "Stream request failed");

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

        let event: Record<string, unknown>;
        try {
          event = JSON.parse(jsonStr) as Record<string, unknown>;
        } catch {
          continue; // Skip malformed JSON lines
        }

        if (event.type === "chunk") {
          setChatMessages((current) =>
            current.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: msg.content + (event.content as string) }
                : msg
            )
          );
        } else if (event.type === "phase" && event.phase === "summarizing") {
          setStatusText("Updating memory scrolls…");
        } else if (event.type === "memories") {
          setRetrievedMemories(event.memories as RetrievedMemory[]);
        } else if (event.type === "quest_update") {
          handleQuestUpdate(event.quest as QuestUpdateNotification, setChatMessages, setStatusText);
        } else if (event.type === "error") {
          throw new Error((event.error as string) || "Stream failed.");
        } else if (event.type === "done") {
          // Best-effort: a failed refetch must not wipe the finished reply.
          await refreshMemory(sessionId).catch(() => {});
        }
      }
    }

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
