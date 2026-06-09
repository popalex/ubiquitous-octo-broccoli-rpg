import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { withUiSpan } from "../telemetry";
import type { ChronicleListItem } from "../types";

export function ChronicleHub() {
  const navigate = useNavigate();
  const [chronicles, setChronicles] = useState<ChronicleListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    void loadChronicles();
  }, []);

  async function loadChronicles() {
    setLoading(true);
    setError(null);
    try {
      const data = await api<{ sessions: ChronicleListItem[] }>("/sessions");
      setChronicles(data.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load chronicles.");
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("Permanently delete this chronicle? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await withUiSpan("ui.delete_chronicle", { "rpg.session_id": id }, () =>
        api(`/session/${id}`, { method: "DELETE" }),
      );
      setChronicles((prev) => prev.filter((c) => c.id !== id));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete chronicle.");
    } finally {
      setDeleting(null);
    }
  }

  function formatDate(iso: string) {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  return (
    <div className="hub-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="masthead hub-masthead">
        <div>
          <p className="eyebrow">Arcane Chronicle</p>
          <h1>✦ The Chronicle Vault</h1>
          <p className="lede">
            Each chronicle is a living record — choose one to continue your story, or open a new tome.
          </p>
        </div>
        {chronicles.length > 0 && (
          <button className="btn-primary hub-new-btn" onClick={() => navigate("/chronicle/new")}>
            <span className="btn-rune">✦</span> Open New Chronicle
          </button>
        )}
      </header>

      <main className="hub-main">
        {loading && (
          <div className="hub-loading">
            <span className="hub-loading-rune">✦</span>
            <p>Consulting the archive…</p>
          </div>
        )}

        {error && (
          <div className="hub-error">
            <p>⚠ {error}</p>
            <button className="btn-ghost" onClick={() => void loadChronicles()}>Retry</button>
          </div>
        )}

        {!loading && !error && chronicles.length === 0 && (
          <div className="hub-empty">
            <div className="hub-empty-icon">📜</div>
            <h2>The vault is empty</h2>
            <p>No chronicles have been written yet. Begin a new adventure.</p>
            <button className="btn-primary hub-empty-btn" onClick={() => navigate("/chronicle/new")}>
              <span className="btn-rune">✦</span> Open New Chronicle
            </button>
          </div>
        )}

        {!loading && !error && chronicles.length > 0 && (
          <div className="hub-grid">
            {chronicles.map((c) => (
              <article
                key={c.id}
                className="chronicle-card"
                onClick={() => navigate(`/chronicle/${c.id}`)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && navigate(`/chronicle/${c.id}`)}
              >
                <div className="chronicle-card-header">
                  <div className="chronicle-card-meta">
                    {c.gm_enabled && <span className="badge badge-gm">GM</span>}
                    <span className="badge badge-turns">{c.turn_count} turns</span>
                  </div>
                </div>

                <h3 className="chronicle-title">{c.title || "Untitled Chronicle"}</h3>

                <div className="chronicle-card-subjects">
                  {c.character_name && (
                    <span className="subject-tag character-tag">
                      <span className="subject-icon">⚔</span> {c.character_name}
                    </span>
                  )}
                  {c.world_name && (
                    <span className="subject-tag world-tag">
                      <span className="subject-icon">🌍</span> {c.world_name}
                    </span>
                  )}
                </div>

                {c.summary && (
                  <p className="chronicle-summary">
                    {c.summary.length > 180 ? c.summary.slice(0, 180) + "…" : c.summary}
                  </p>
                )}

                <footer className="chronicle-card-footer">
                  <span className="chronicle-date">Last played {formatDate(c.updated_at)}</span>
                  <div className="chronicle-footer-actions">
                    <button
                      className="chronicle-delete-btn"
                      disabled={deleting === c.id}
                      onClick={(e) => void handleDelete(c.id, e)}
                    >
                      {deleting === c.id ? "…" : "Delete"}
                    </button>
                    <span className="chronicle-resume">Continue →</span>
                  </div>
                </footer>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
