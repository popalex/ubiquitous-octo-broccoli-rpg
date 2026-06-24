import { Sparkle } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { sendChat } from "../chat";
import {
  useRefreshMemory,
  useSessionDetail,
  useSessionMemory,
  useSessionQuests,
  useSessionSheet,
  useSessionSuggestions,
  useSessionTurns,
  useWorldState,
} from "../hooks/useSession";
import { useForkSession } from "../hooks/useSessionMutations";
import { turnsToMessages } from "../turns";
import type { ChatMessage, GMEvent, RetrievedMemory, SessionDetail, TurnRecord } from "../types";
import { ChatPanel } from "./ChatPanel";
import { CharacterSheetPanel } from "./CharacterSheetPanel";
import { CodexPanel } from "./CodexPanel";
import { MemoryPanel } from "./MemoryPanel";
import { QuestJournal } from "./QuestJournal";
import { ErrorBanner } from "./ui/ErrorBanner";
import { Spinner } from "./ui/Spinner";

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
        <ErrorBanner
          message={error?.message || "Failed to load chronicle."}
          onRetry={() => {
            void detail.refetch();
            void turns.refetch();
          }}
        />
      </main>
    );
  }

  if (!detail.data || !turns.data) {
    return (
      <main className="dashboard dashboard-chronicle">
        <Spinner label="Loading chronicle…" />
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
  const navigate = useNavigate();
  const starterPrompt = (location.state as { starter?: string } | null)?.starter ?? "";

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(() => turnsToMessages(initialTurns));
  const [chatInput, setChatInput] = useState(starterPrompt);
  const [retrievedMemories, setRetrievedMemories] = useState<RetrievedMemory[]>([]);
  const [continuityIssues, setContinuityIssues] = useState<string[]>([]);
  const [, setLastEvent] = useState<GMEvent | null>(null);
  const baseStatus = `Chronicle ${detail.gm_enabled ? "GM Mode" : "Standard"}. ${detail.turn_count} turns recorded.`;
  const [statusText, setStatusText] = useState(baseStatus);
  const [isBusy, setIsBusy] = useState(false);

  const memory = useSessionMemory(sessionId);
  const worldState = useWorldState(sessionId);
  const quests = useSessionQuests(sessionId);
  const sheet = useSessionSheet(sessionId, detail.character_sheet_enabled);
  const suggestions = useSessionSuggestions(sessionId, detail.suggestions_enabled);
  const refreshMemory = useRefreshMemory();
  const forkSession = useForkSession();
  const [forkingTurn, setForkingTurn] = useState<number | null>(null);

  const gmEnabled = detail.gm_enabled;
  const currentLocation = detail.current_location || "";
  const timeOfDay = detail.time_of_day || "morning";

  // Regenerated-on-load chips. Derived (never setState-in-effect): attach the
  // loaded suggestions to the reply they were generated for — the latest
  // non-user turn at load. A later live turn carries a fresh id, so stale chips
  // never bleed onto it, and only the last message renders chips anyway.
  const loadedReplyId = useMemo(() => {
    for (let i = initialTurns.length - 1; i >= 0; i--) {
      if (initialTurns[i].role !== "user") return `${initialTurns[i].turn_index}`;
    }
    return null;
  }, [initialTurns]);
  const displayMessages = useMemo(() => {
    const chips = suggestions.data?.suggestions;
    if (!chips?.length || !loadedReplyId) return chatMessages;
    return chatMessages.map((m) =>
      m.id === loadedReplyId && !m.suggestions?.length ? { ...m, suggestions: chips } : m,
    );
  }, [chatMessages, suggestions.data, loadedReplyId]);

  // On reload, chips aren't persisted — `useSessionSuggestions` fires a fresh
  // (slow) judge call. Overlay that lifecycle onto the status bar so the user
  // knows chips are coming, then that they've arrived. Derived (never
  // setState-in-effect); `isBusy` yields the bar to the live chat flow, which
  // owns `statusText` while a turn streams.
  const displayStatus = useMemo(() => {
    if (isBusy) return statusText;
    if (detail.suggestions_enabled && suggestions.isLoading) {
      return `${baseStatus} Summoning suggested replies…`;
    }
    if (detail.suggestions_enabled && suggestions.isSuccess && suggestions.data?.suggestions?.length) {
      return `${baseStatus} Suggested replies ready.`;
    }
    return statusText;
  }, [
    isBusy,
    statusText,
    baseStatus,
    detail.suggestions_enabled,
    suggestions.isLoading,
    suggestions.isSuccess,
    suggestions.data,
  ]);

  function handleForkFromTurn(turnIndex: number) {
    if (forkingTurn != null) return;
    if (!confirm(`Fork a new chronicle from turn ${turnIndex}? The original is left untouched.`)) return;
    setForkingTurn(turnIndex);
    forkSession.mutate(
      { sessionId, atTurn: turnIndex },
      {
        onSuccess: (fork) => navigate(`/chronicle/${fork.id}`),
        onError: (err) => {
          alert(err instanceof Error ? err.message : "Failed to fork chronicle.");
          setForkingTurn(null);
        },
      },
    );
  }

  function handleSendChat(messageOverride?: string) {
    void sendChat({
      sessionId,
      chatInput: messageOverride ?? chatInput,
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
            {gmEnabled ? (
              <>
                <Sparkle className="inline-icon" /> Game Master
              </>
            ) : (
              "Standard"
            )}
          </strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">World Ledger</span>
          <strong>{detail.world_state_enabled ? "On" : "Off"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Quests</span>
          <strong>{detail.quests_enabled ? "On" : "Off"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Suggestions</span>
          <strong>{detail.suggestions_enabled ? "On" : "Off"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Dice</span>
          <strong>{detail.dice_enabled ? "On" : "Off"}</strong>
        </div>
        <div className="summary-item">
          <span className="meta-label">Sheet</span>
          <strong>{detail.character_sheet_enabled ? "On" : "Off"}</strong>
        </div>
      </div>
      <main className="dashboard dashboard-chronicle">
        <ChatPanel
          chatMessages={displayMessages}
          chatInput={chatInput}
          setChatInput={setChatInput}
          isBusy={isBusy}
          sessionId={sessionId}
          characterName={detail.character_name || ""}
          statusText={displayStatus}
          onSendChat={handleSendChat}
          onForkFromTurn={handleForkFromTurn}
          forkingTurn={forkingTurn}
        />
        <div className="panel-stack">
          {detail.character_sheet_enabled && <CharacterSheetPanel sheet={sheet.data ?? detail.sheet ?? null} />}
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
