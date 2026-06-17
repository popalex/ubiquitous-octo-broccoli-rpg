import { describe, expect, it } from "vitest";

import { attachSuggestionsToLatestReply, cleanSuggestions } from "./suggestions";
import type { ChatMessage } from "./types";

const msg = (id: string, role: ChatMessage["role"]): ChatMessage => ({ id, role, content: id });

describe("cleanSuggestions", () => {
  it("keeps only non-empty strings", () => {
    expect(cleanSuggestions(["  Run ", "", "   ", 42, null, "Hide"])).toEqual(["  Run ", "Hide"]);
  });

  it("returns [] for non-array payloads", () => {
    expect(cleanSuggestions("not a list")).toEqual([]);
    expect(cleanSuggestions(undefined)).toEqual([]);
  });
});

describe("attachSuggestionsToLatestReply", () => {
  it("attaches to the most recent assistant/narrator message", () => {
    const messages = [msg("1", "user"), msg("2", "assistant"), msg("3", "narrator"), msg("4", "user")];
    const out = attachSuggestionsToLatestReply(messages, ["a", "b"]);
    expect(out[2].suggestions).toEqual(["a", "b"]); // the narrator, latest non-user
    expect(out[1].suggestions).toBeUndefined();
  });

  it("returns the same reference when there is no reply or no suggestions", () => {
    const onlyUsers = [msg("1", "user")];
    expect(attachSuggestionsToLatestReply(onlyUsers, ["a"])).toBe(onlyUsers);
    const withReply = [msg("1", "assistant")];
    expect(attachSuggestionsToLatestReply(withReply, [])).toBe(withReply);
  });
});
