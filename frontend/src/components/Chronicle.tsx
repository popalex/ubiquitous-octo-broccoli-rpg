import { useState } from "react";
import { useLocation } from "react-router-dom";

import { sendChat } from "../chat";
import { useHealth } from "../hooks/useHealth";
import {
  useRefreshMemory,
  useSessionDetail,
  useSessionMemory,
  useSessionQuests,
  useSessionTurns,
  useWorldState,
} from "../hooks/useSession";
import { turnsToMessages } from "../turns";
import type { ChatMessage, GMEvent, RetrievedMemory, SessionDetail, TurnRecord } from "../types";
import { ChatPanel } from "./ChatPanel";
import { CodexPanel } from "./CodexPanel";
import { MemoryPanel } from "./MemoryPanel";
import { QuestJournal } from "./QuestJournal";

/**
 * Loads a chronicle's detail + turns via React Query, then hands the resolved
 * data to {@link ChronicleView} (remounted per session via `key`) which owns
 * the live chat state seeded from those turns.
 */
export function Chronicle({ sessionId }: { sessionId: string }) {
  const detail = useSessionDetail(sessionId);
  const turns = useSessionTurns(sessionId);

  if (detail.isError || turns.isError) {
    const error = (detail.error ?? turns.error) as Error | null;
    return (
      <main className="dashboard dashboard-chronicle">
        <p className="muted">{error?.message || "Failed to load chronicle."}</p>
      </main>
    );
  }

  if (!detail.data || !turns.data) {
    return (
      <main className="dashboard dashboard-chronicle">
        <p className="muted">Loading chronicle…</p>
      </main>
    );
  }

  return <ChronicleView key={sessionId} sessionId={sessionId} detail={detail.data} initialTurns={turns.data} />;
}

type ViewProps = {
  sessionId: string;
  detail: SessionDetail;
  initialTurns: TurnRecord[];
};

function ChronicleView({ sessionId, detail, initialTurns }: ViewProps) {
  const location = useLocation();
  const starterPrompt = (location.state as { starter?: string } | null)?.starter ?? "";

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(() => turnsToMessages(initialTurns));
  const [chatInput, setChatInput] = useState(starterPrompt);
  const [retrievedMemories, setRetrievedMemories] = useState<RetrievedMemory[]>([]);
  const [continuityIssues, setContinuityIssues] = useState<string[]>([]);
  const [, setLastEvent] = useState<GMEvent | null>(null);
  const [statusText, setStatusText] = useState(
    `Chronicle ${detail.gm_enabled ? "GM Mode" : "Standard"}. ${detail.turn_count} turns recorded.`,
  );
  const [isBusy, setIsBusy] = useState(false);

  const health = useHealth();
  const memory = useSessionMemory(sessionId);
  const worldState = useWorldState(sessionId);
  const quests = useSessionQuests(sessionId);
  const refreshMemory = useRefreshMemory();

  const gmEnabled = detail.gm_enabled;
  const currentLocation = detail.current_location || "";
  const timeOfDay = detail.time_of_day || "morning";

  function handleSendChat() {
    void sendChat({
      sessionId,
      chatInput,
      setChatInput,
      gmEnabled,
      currentLocation,
      timeOfDay,
      setChatMessages,
      setRetrievedMemories,
      setContinuityIssues,
      setLastEvent,
      setStatusText,
      setIsBusy,
      refreshMemory,
    });
  }

  return (
    <>
      <div className="chronicle-summary-bar">
        <div className="summary-item">
          <span className="meta-label">Protagonist</span>
          <strong>{detail.character_name || "—"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Realm</span>
          <strong>{detail.world_name || "—"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Chronicle</span>
          <strong>{sessionId ? `#${sessionId.slice(0, 8)}` : "Awaiting"}</strong>
        </div>
        {gmEnabled && (
          <div className="summary-item">
            <span className="meta-label">Location</span>
            <strong>{currentLocation || "—"}</strong>
          </div>
        )}
        <div className="summary-item">
          <span className="meta-label">Mode</span>
          <strong className={gmEnabled ? "gm-badge" : undefined}>
            {gmEnabled ? "✧ Game Master" : "Standard"}
          </strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">World Ledger</span>
          <strong>{health ? (health.world_state_enabled ? "On" : "Off") : "—"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Quests</span>
          <strong>{health ? (health.quests_enabled ? "On" : "Off") : "—"}</strong>
        </div>
      </div>
      <main className="dashboard dashboard-chronicle">
        <ChatPanel
          chatMessages={chatMessages}
          chatInput={chatInput}
          setChatInput={setChatInput}
          isBusy={isBusy}
          sessionId={sessionId}
          characterName={detail.character_name || ""}
          statusText={statusText}
          onSendChat={handleSendChat}
        />
        <div className="panel-stack">
          <CodexPanel worldState={worldState.data ?? null} />
          <QuestJournal sessionId={sessionId} quests={quests.data ?? null} />
          <MemoryPanel
            retrievedMemories={retrievedMemories}
            continuityIssues={continuityIssues}
            memory={memory.data ?? null}
          />
        </div>
      </main>
    </>
  );
}
