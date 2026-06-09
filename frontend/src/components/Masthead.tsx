import type { Health } from "../types";

type Props = {
  phase: "codex" | "chronicle";
  health: Health | null;
  onHome: () => void;
};

export function Masthead({ phase, health, onHome }: Props) {
  return (
    <header className="masthead">
      <div>
        <p className="eyebrow">Arcane Chronicle</p>
        {phase === "codex" ? (
          <>
            <h1>
              <button type="button" className="title-home" onClick={onHome} title="Return to the Vault">
                ✦ Character Codex
              </button>
            </h1>
            <p className="lede">
              Craft your character, choose your world, and prepare for the adventure ahead.
            </p>
          </>
        ) : (
          <>
            <h1>
              <button type="button" className="title-home" onClick={onHome} title="Return to the Vault">
                ✦ Live Chronicle
              </button>
            </h1>
            <p className="lede">Your story unfolds — speak and the world responds.</p>
          </>
        )}
      </div>
      <div className="status-strip">
        <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}>Realm {health?.status || "..."}</div>
        <div className={`pill ${health?.database === "ok" ? "ok" : "warn"}`}>Archive {health?.database || "..."}</div>
        <div className={`pill ${health?.mode === "DEV" ? "warn" : "ok"}`}>{health?.mode || "..."}</div>
        <div className="pill neutral">Local Models</div>
        <div className="pill neutral">Ollama</div>
      </div>
    </header>
  );
}
