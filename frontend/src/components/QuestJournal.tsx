import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { sessionKeys } from "../hooks/useSession";
import type { Quest, SessionQuests } from "../types";

type Props = {
  sessionId: string;
  quests: SessionQuests | null;
};

const OPEN_STATUSES = ["rumored", "offered", "active", "escalating"];

const TYPE_GLYPHS: Record<string, string> = {
  mystery: "🜁 mystery",
  promise: "✦ promise",
  social: "✧ social arc",
  dilemma: "⚖ dilemma",
  threat: "☄ threat",
};

export function QuestJournal({ sessionId, quests }: Props) {
  const queryClient = useQueryClient();
  const abandon = useMutation({
    mutationFn: (questId: string) =>
      api<Quest>(`/session/${sessionId}/quests/${questId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "abandoned" }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sessionKeys.quests(sessionId) }),
  });

  const all = quests?.quests ?? [];
  const active = all.filter((q) => q.status === "active" || q.status === "escalating");
  const offered = all.filter((q) => q.status === "rumored" || q.status === "offered");
  const concluded = all.filter((q) => !OPEN_STATUSES.includes(q.status));

  return (
    <section className="panel panel-right">
      <div className="panel-header">
        <p className="eyebrow">Story Arcs</p>
        <h2>The Journal</h2>
      </div>

      {all.length === 0 ? (
        <p className="muted">No arcs bind you yet...</p>
      ) : (
        <div className="stack">
          {active.length > 0 && (
            <div className="subpanel">
              <h3>✦ Active Arcs</h3>
              {active.map((q) => (
                <QuestCard key={q.id} quest={q} onAbandon={() => abandon.mutate(q.id)} />
              ))}
            </div>
          )}

          {offered.length > 0 && (
            <div className="subpanel">
              <h3>✧ Whispers &amp; Offers</h3>
              {offered.map((q) => (
                <QuestCard key={q.id} quest={q} />
              ))}
            </div>
          )}

          {concluded.length > 0 && (
            <details className="subpanel concluded-arcs">
              <summary className="subpanel-summary">
                <h3>♦ Concluded ({concluded.length})</h3>
              </summary>
              {concluded.map((q) => (
                <div key={q.id} className="memory-card">
                  <div className="memory-topline">
                    <span>{TYPE_GLYPHS[q.quest_type] ?? q.quest_type}</span>
                    <span>{q.status}</span>
                  </div>
                  <p>
                    <strong>{q.title}</strong>
                    {q.resolution ? ` — ${q.resolution}` : ""}
                  </p>
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </section>
  );
}

function QuestCard({ quest, onAbandon }: { quest: Quest; onAbandon?: () => void }) {
  const escalating = quest.status === "escalating";
  return (
    <div className={escalating ? "issue-card" : "memory-card"}>
      <div className="memory-topline">
        <span>{TYPE_GLYPHS[quest.quest_type] ?? quest.quest_type}</span>
        <span>{escalating ? "⚠ escalating" : quest.status}</span>
      </div>
      <p>
        <strong>{quest.title}</strong> — {quest.description}
      </p>
      {quest.stakes && (
        <p className="muted">
          <em>At stake: {quest.stakes}</em>
        </p>
      )}
      {quest.stages.length > 0 && (
        <ul className="quest-stages">
          {quest.stages.map((s) => (
            <li key={s.id} className={s.done ? "muted" : undefined}>
              {s.done ? "✓" : "•"} {s.description}
            </li>
          ))}
        </ul>
      )}
      {onAbandon && (
        <button type="button" className="btn btn-secondary quest-abandon" onClick={onAbandon}>
          Abandon
        </button>
      )}
    </div>
  );
}
