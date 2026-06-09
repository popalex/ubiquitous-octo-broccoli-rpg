import type { ChatMessage, TurnRecord } from "./types";

/** Map persisted turns to the chat-message shape used by the UI. */
export function turnsToMessages(turns: TurnRecord[]): ChatMessage[] {
  return turns.map((t) => ({
    id: `${t.turn_index}`,
    role: (t.role === "user"
      ? "user"
      : t.turn_type === "gm_narration" || t.turn_type === "gm_event"
        ? "narrator"
        : "assistant") as ChatMessage["role"],
    content: t.content,
    messageType: (t.turn_type === "gm_narration"
      ? "pre_narration"
      : t.turn_type === "gm_event"
        ? "event"
        : "chat") as ChatMessage["messageType"],
  }));
}
