import type { ChatMessage } from "./types";

/** Keep only non-empty strings from a raw suggestions payload (a bad frame or
 *  malformed response must never disrupt the finished reply). */
export function cleanSuggestions(suggestions: unknown): string[] {
  if (!Array.isArray(suggestions)) return [];
  return suggestions.filter((s): s is string => typeof s === "string" && s.trim() !== "");
}

/** Return a copy of `messages` with `suggestions` set on the most recent
 *  assistant/narrator message (in GM mode a narrator event may follow the
 *  reply). Returns the same array reference when there is no reply to attach to
 *  or `suggestions` is empty. */
export function attachSuggestionsToLatestReply(messages: ChatMessage[], suggestions: string[]): ChatMessage[] {
  if (suggestions.length === 0) return messages;
  let target = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant" || messages[i].role === "narrator") {
      target = i;
      break;
    }
  }
  if (target === -1) return messages;
  return messages.map((msg, i) => (i === target ? { ...msg, suggestions } : msg));
}
