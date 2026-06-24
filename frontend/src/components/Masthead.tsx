import { Sparkles } from "lucide-react";

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
        <p className="eyebrow">
          <span className="eyebrow-vault">
            <button type="button" className="vault-link" onClick={onHome}>The Vault</button>
          </span>
          <span aria-hidden="true"> / </span>
          Arcane Chronicle
        </p>
        <h1>
          <button type="button" className="title-home" onClick={onHome} title={`Return to the Vault — ${phase === "codex" ? "Character Codex" : "Live Chronicle"}`}>
            <Sparkles className="inline-icon" />{" "}
            {phase === "codex" ? "Character Codex" : "Live Chronicle"}
          </button>
        </h1>
        <p className="lede">
          {phase === "codex"
            ? "Craft your character, choose your world, and prepare for the adventure ahead."
            : "Your story unfolds — speak and the world responds."}
        </p>
      </div>
      <div className="masthead-status">
        <div className="status-strip" role="status" aria-live="polite">
          <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}>
            <span className="sr-only">{health?.status === "ok" ? "Connected" : "Disconnected"}</span>
            Realm {health?.status || "..."}
          </div>
          <div className={`pill ${health?.database === "ok" ? "ok" : "warn"}`}>
            <span className="sr-only">{health?.database === "ok" ? "Connected" : "Disconnected"}</span>
            Archive {health?.database || "..."}
          </div>
          <div className={`pill ${health?.mode === "DEV" ? "warn" : "ok"}`}>
            <span className="sr-only">{health?.mode === "DEV" ? "Development mode" : "Production mode"}</span>
            {health?.mode || "..."}
          </div>
        </div>
        {health && (
          <div className="status-strip models-strip" aria-label="Active models">
            <div className="pill neutral" title="In-character actor model">
              Actor · {health.actor_model}
            </div>
            <div className="pill neutral" title="Game Master model">
              GM · {health.gm_model}
            </div>
            <div className="pill neutral" title="Memory / world-state / quests model">
              Memory · {health.memory_model}
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
