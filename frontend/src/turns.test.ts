import { describe, expect, it } from "vitest";

import { turnsToMessages } from "./turns";

describe("turnsToMessages", () => {
  it("maps user turns to the user role / chat type", () => {
    const [msg] = turnsToMessages([{ turn_index: 1, role: "user", content: "hi", turn_type: "chat" }]);
    expect(msg).toMatchObject({ id: "1", role: "user", content: "hi", messageType: "chat" });
  });

  it("maps assistant chat turns to the assistant role", () => {
    const [msg] = turnsToMessages([{ turn_index: 2, role: "assistant", content: "yo", turn_type: "chat" }]);
    expect(msg).toMatchObject({ role: "assistant", messageType: "chat" });
  });

  it("maps GM narration and events to the narrator role", () => {
    const [narration, event] = turnsToMessages([
      { turn_index: 3, role: "assistant", content: "scene", turn_type: "gm_narration" },
      { turn_index: 4, role: "assistant", content: "boom", turn_type: "gm_event" },
    ]);
    expect(narration).toMatchObject({ role: "narrator", messageType: "pre_narration" });
    expect(event).toMatchObject({ role: "narrator", messageType: "event" });
  });

  it("preserves order and indexes ids by turn_index", () => {
    const messages = turnsToMessages([
      { turn_index: 5, role: "user", content: "a", turn_type: "chat" },
      { turn_index: 6, role: "assistant", content: "b", turn_type: "chat" },
    ]);
    expect(messages.map((m) => m.id)).toEqual(["5", "6"]);
  });
});
