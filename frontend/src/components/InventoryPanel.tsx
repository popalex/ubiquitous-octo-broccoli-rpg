import { Backpack, FlaskConical, Sword } from "lucide-react";

import type { Item } from "../types";

type Props = {
  items: Item[] | null;
  onEquip?: (itemId: string, equipped: boolean) => void;
  onUse?: (itemId: string) => void;
  busyItemId?: string | null;
};

/** Effect → short human label shown under the item name. */
function effectLabel(item: Item): string | null {
  if (item.effect_type === "check_bonus") {
    const scope = item.effect_attribute ? ` ${item.effect_attribute.toUpperCase()}` : "";
    return `+${item.effect_value}${scope} on checks`;
  }
  if (item.effect_type === "heal") return `restores ${item.effect_value} HP`;
  return null;
}

/** Read-only-ish inventory (todo-rpg Phase 4): structured items with their
 * mechanical effect, an Equip toggle for gear and a Use button for consumables. */
export function InventoryPanel({ items, onEquip, onUse, busyItemId = null }: Props) {
  return (
    <section className="panel panel-right">
      <div className="panel-header">
        <p className="eyebrow">Inventory</p>
        <h2>The Pack</h2>
        {items && items.length > 0 && <span className="muted">{items.length} items</span>}
      </div>

      {!items || items.length === 0 ? (
        <p className="muted">Nothing of note yet — loot and gear gathered in play appear here.</p>
      ) : (
        <div className="stack">
          {items.map((item) => {
            const label = effectLabel(item);
            const Icon = item.consumable ? FlaskConical : item.effect_type === "check_bonus" ? Sword : Backpack;
            const busy = busyItemId === item.id;
            return (
              <div className={`inv-item${item.equipped ? " inv-item-equipped" : ""}`} key={item.id}>
                <span className="inv-item-icon" aria-hidden="true">
                  <Icon className="inline-icon" />
                </span>
                <span className="inv-item-text">
                  <span className="inv-item-name">
                    {item.name}
                    {item.qty > 1 ? ` ×${item.qty}` : ""}
                    {item.equipped ? " (equipped)" : ""}
                  </span>
                  {label && <span className="inv-item-effect">{label}</span>}
                  {!label && item.description && <span className="inv-item-effect">{item.description}</span>}
                </span>
                {item.consumable && onUse && (
                  <button type="button" className="inv-item-btn" onClick={() => onUse(item.id)} disabled={busy}>
                    {busy ? "…" : "Use"}
                  </button>
                )}
                {!item.consumable && item.effect_type === "check_bonus" && onEquip && (
                  <button
                    type="button"
                    className="inv-item-btn"
                    onClick={() => onEquip(item.id, !item.equipped)}
                    disabled={busy}
                  >
                    {busy ? "…" : item.equipped ? "Unequip" : "Equip"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
