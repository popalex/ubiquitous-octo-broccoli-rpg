import type { RetrievedMemory, SessionMemory } from "../types";

type Props = {
  retrievedMemories: RetrievedMemory[];
  continuityIssues: string[];
  memory: SessionMemory | null;
};

export function MemoryPanel({ retrievedMemories, continuityIssues, memory }: Props) {
  return (
    <section className="panel panel-right">
      <div className="panel-header">
        <p className="eyebrow">Memory Vault</p>
        <h2>The Archive</h2>
      </div>

      <div className="stack">
        <div className="subpanel">
          <h3>✧ Retrieved Echoes</h3>
          {retrievedMemories.length === 0 ? (
            <p className="muted">No memories stirred this turn...</p>
          ) : (
            retrievedMemories.map((item) => (
              <div key={item.id} className="memory-card">
                <div className="memory-topline">
                  <span>{item.kind}</span>
                  <span>{item.weighted_score.toFixed(2)}</span>
                </div>
                <p>{item.content}</p>
              </div>
            ))
          )}
        </div>

        <div className="subpanel">
          <h3>⚠ Continuity Rifts</h3>
          {continuityIssues.length === 0 ? (
            <p className="muted">The timeline flows true...</p>
          ) : (
            continuityIssues.map((issue) => (
              <div key={issue} className="issue-card">
                {issue}
              </div>
            ))
          )}
        </div>

        <div className="subpanel">
          <h3>✦ Eternal Truths</h3>
          {memory?.facts.length ? (
            memory.facts.slice(0, 8).map((fact) => (
              <div key={fact.id} className="memory-card">
                <div className="memory-topline">
                  <span>fact</span>
                  <span>{fact.importance.toFixed(2)}</span>
                </div>
                <p>{fact.content}</p>
              </div>
            ))
          ) : (
            <p className="muted">Facts crystallize after several turns...</p>
          )}
        </div>

        <div className="subpanel">
          <h3>✧ Episode Scrolls</h3>
          {memory?.episode_summaries.length ? (
            memory.episode_summaries.slice(0, 4).map((summary) => (
              <div key={summary.id} className="memory-card">
                <div className="memory-topline">
                  <span>
                    turns {summary.start_turn_index}–{summary.end_turn_index}
                  </span>
                  <span>{summary.importance.toFixed(2)}</span>
                </div>
                <p>{summary.content}</p>
              </div>
            ))
          ) : (
            <p className="muted">No scrolls penned yet...</p>
          )}
        </div>
      </div>
    </section>
  );
}
