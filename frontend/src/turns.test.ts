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

  it("re-renders a roll chip just before the turn it resolved", () => {
    const messages = turnsToMessages([
      {
        turn_index: 7,
        role: "assistant",
        content: "You slip past.",
        turn_type: "chat",
        roll: {
          skill_label: "Stealth",
          dc: 15,
          die: 4,
          attribute: null,
          modifier: 0,
          total: 4,
          outcome: "failure",
          rationale: "alert guard",
        },
      },
    ]);
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ id: "roll-7", role: "narrator", messageType: "roll" });
    expect(messages[0].roll).toMatchObject({ skill_label: "Stealth", outcome: "failure" });
    expect(messages[1]).toMatchObject({ id: "7", content: "You slip past." });
  });
});
