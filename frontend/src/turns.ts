import type { ChatMessage, TurnRecord } from "./types";

/** Map persisted turns to the chat-message shape used by the UI. */
export function turnsToMessages(turns: TurnRecord[]): ChatMessage[] {
  return turns.flatMap((t) => {
    const message: ChatMessage = {
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
    };
    const messages: ChatMessage[] = [];
    // A resolved skill check re-renders as a chip just before the turn it
    // resolved (matching the live order: scene → roll → outcome).
    if (t.roll) {
      const verdict = t.roll.outcome.replace("_", " ");
      messages.push({
        id: `roll-${t.turn_index}`,
        role: "narrator",
        content: `Skill check — ${t.roll.skill_label} vs DC ${t.roll.dc}: rolled ${t.roll.die} (${verdict})`,
        messageType: "roll",
        roll: t.roll,
      });
    }
    messages.push(message);
    // Level-up beats this turn produced re-render as a card just after the reply
    // (matching the live order: reply → advancement).
    if (t.advancement && t.advancement.length > 0) {
      messages.push({
        id: `advancement-${t.turn_index}`,
        role: "narrator",
        content: `**${t.advancement.join(" ")}**`,
        messageType: "advancement",
      });
    }
    return messages;
  });
}
