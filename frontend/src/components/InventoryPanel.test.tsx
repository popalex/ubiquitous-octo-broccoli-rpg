import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Item } from "../types";
import { InventoryPanel } from "./InventoryPanel";

function item(overrides: Partial<Item> = {}): Item {
  return {
    id: "i1",
    name: "Thing",
    description: null,
    qty: 1,
    equipped: false,
    consumable: false,
    effect_type: null,
    effect_value: 0,
    effect_attribute: null,
    ...overrides,
  };
}

describe("InventoryPanel", () => {
  it("shows the empty state without items", () => {
    render(<InventoryPanel items={[]} />);
    expect(screen.getByText(/Nothing of note yet/i)).toBeInTheDocument();
  });

  it("renders an equippable item with its effect and an Equip button", () => {
    const onEquip = vi.fn();
    render(
      <InventoryPanel
        items={[item({ id: "lp", name: "Fine Lockpick", effect_type: "check_bonus", effect_value: 2, effect_attribute: "finesse" })]}
        onEquip={onEquip}
      />,
    );
    expect(screen.getByText("Fine Lockpick")).toBeInTheDocument();
    expect(screen.getByText("+2 FINESSE on checks")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /equip/i }));
    expect(onEquip).toHaveBeenCalledWith("lp", true);
  });

  it("offers Unequip for equipped gear", () => {
    const onEquip = vi.fn();
    render(
      <InventoryPanel items={[item({ id: "lp", equipped: true, effect_type: "check_bonus", effect_value: 1 })]} onEquip={onEquip} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /unequip/i }));
    expect(onEquip).toHaveBeenCalledWith("lp", false);
  });

  it("renders a consumable with a Use button", () => {
    const onUse = vi.fn();
    render(
      <InventoryPanel
        items={[item({ id: "po", name: "Potion", consumable: true, effect_type: "heal", effect_value: 6, qty: 2 })]}
        onUse={onUse}
      />,
    );
    expect(screen.getByText(/Potion ×2/)).toBeInTheDocument();
    expect(screen.getByText("restores 6 HP")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /use/i }));
    expect(onUse).toHaveBeenCalledWith("po");
  });
});
