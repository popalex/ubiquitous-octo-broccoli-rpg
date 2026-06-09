import type { WorldStateLedger } from "../types";

type Props = {
  worldState: WorldStateLedger | null;
};

export function CodexPanel({ worldState }: Props) {
  const state = worldState?.state;
  const version = worldState?.version ?? 0;

  const location = state?.location;
  const entities = state?.entities ?? [];
  const inventory = state?.inventory ?? [];
  const threads = state?.threads ?? [];
  const facts = state?.facts ?? [];

  const dead = entities.filter((e) => (e.status ?? "").toLowerCase() === "dead");
  const living = entities.filter((e) => (e.status ?? "").toLowerCase() !== "dead");
  const openThreads = threads.filter((t) => (t.status ?? "").toLowerCase() !== "resolved");

  const hasLocation = !!(location?.name || location?.description);

  const isEmpty =
    !hasLocation && !entities.length && !inventory.length && !threads.length && !facts.length;

  return (
    <section className="panel panel-right">
      <div className="panel-header">
        <p className="eyebrow">World State Ledger</p>
        <h2>The Codex</h2>
        {version > 0 && <span className="muted">canon v{version}</span>}
      </div>

      {isEmpty ? (
        <p className="muted">Canon accretes as the story unfolds...</p>
      ) : (
        <div className="stack">
          {hasLocation && (
            <div className="subpanel">
              <h3>✦ Location</h3>
              <div className="memory-card">
                <p>
                  {location?.name ? <strong>{location.name}</strong> : null}
                  {location?.description
                    ? `${location?.name ? " — " : ""}${location.description}`
                    : ""}
                </p>
              </div>
            </div>
          )}
          {dead.length > 0 && (
            <div className="subpanel">
              <h3>☠ The Fallen</h3>
              {dead.map((e) => (
                <div key={e.id} className="issue-card">
                  {e.name} — dead
                </div>
              ))}
            </div>
          )}

          {living.length > 0 && (
            <div className="subpanel">
              <h3>✧ Dramatis Personae</h3>
              {living.map((e) => (
                <div key={e.id} className="memory-card">
                  <div className="memory-topline">
                    <span>{e.kind || "npc"}</span>
                    {e.relationship_to_player && <span>{e.relationship_to_player}</span>}
                  </div>
                  <p>
                    <strong>{e.name}</strong>
                    {e.status ? ` (${e.status})` : ""}
                    {e.facts?.length ? ` — ${e.facts.join("; ")}` : ""}
                  </p>
                </div>
              ))}
            </div>
          )}

          {inventory.length > 0 && (
            <div className="subpanel">
              <h3>✦ Inventory</h3>
              <div className="memory-card">
                <p>
                  {inventory
                    .map((item) => (item.qty != null ? `${item.item} ×${item.qty}` : item.item))
                    .join(", ")}
                </p>
              </div>
            </div>
          )}

          {openThreads.length > 0 && (
            <div className="subpanel">
              <h3>✧ Open Threads</h3>
              {openThreads.map((t) => (
                <div key={t.id} className="memory-card">
                  <p>{t.summary}</p>
                </div>
              ))}
            </div>
          )}

          {facts.length > 0 && (
            <div className="subpanel">
              <h3>✦ Canon Facts</h3>
              {facts.map((fact) => (
                <div key={fact} className="memory-card">
                  <p>{fact}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
