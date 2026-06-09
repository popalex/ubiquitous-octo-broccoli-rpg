import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { templates as baseTemplates } from "./templates";
import { loadAllTemplates } from "./loadTemplates";
import { api, storageKeys, createInitialForm } from "./api";
import { sendChat } from "./chat";
import { withUiSpan } from "./telemetry";
import { CharacterPanel } from "./components/CharacterPanel";
import { ChatPanel } from "./components/ChatPanel";
import { CodexPanel } from "./components/CodexPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import type {
  CharacterLoadPayload,
  ChatMessage,
  GMEvent,
  Health,
  RetrievedMemory,
  SessionDetail,
  SessionMemory,
  TurnRecord,
  WorldStateLedger,
} from "./types";

export default function App() {
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  // When arriving at an existing chronicle, skip template auto-fill from the start
  const [sessionResumed, setSessionResumed] = useState(!!routeSessionId);

  const [allTemplates, setAllTemplates] = useState(baseTemplates);
  const [selectedTemplateId, setSelectedTemplateId] = useState(
    localStorage.getItem(storageKeys.selectedTemplate) || baseTemplates[0].id,
  );
  const [form, setForm] = useState<CharacterLoadPayload>(createInitialForm);
  const [health, setHealth] = useState<Health | null>(null);
  const [statusText, setStatusText] = useState("Ready.");
  const [isBusy, setIsBusy] = useState(false);
  const [sessionTitle, setSessionTitle] = useState(localStorage.getItem(storageKeys.sessionTitle) || baseTemplates[0].sessionTitle);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [retrievedMemories, setRetrievedMemories] = useState<RetrievedMemory[]>([]);
  const [continuityIssues, setContinuityIssues] = useState<string[]>([]);
  const [memory, setMemory] = useState<SessionMemory | null>(null);
  const [worldState, setWorldState] = useState<WorldStateLedger | null>(null);
  const [ids, setIds] = useState({
    characterCardId: localStorage.getItem(storageKeys.characterCardId) || "",
    worldStateId: localStorage.getItem(storageKeys.worldStateId) || "",
    sessionId: routeSessionId || "",
  });

  // GM Mode state
  const [gmEnabled, setGmEnabled] = useState(localStorage.getItem(storageKeys.gmEnabled) === "true");
  const [currentLocation, setCurrentLocation] = useState("");
  const [timeOfDay, setTimeOfDay] = useState("morning");
  const [, setLastEvent] = useState<GMEvent | null>(null);

  useEffect(() => {
    loadAllTemplates().then(setAllTemplates);
  }, []);

  // Restore existing chronicle state when a sessionId is in the URL
  useEffect(() => {
    if (!routeSessionId) return;
    setIsBusy(true);
    setStatusText("Loading chronicle…");

    async function resumeSession() {
      try {
        // Load session detail and turns first (fast, critical for display).
        const [detail, turnsRaw] = await Promise.all([
          api<SessionDetail>(`/session/${routeSessionId}`),
          api<TurnRecord[]>(`/session/${routeSessionId}/turns`),
        ]);

        setIds({
          characterCardId: detail.character_card_id,
          worldStateId: detail.world_state_id || "",
          sessionId: detail.id,
        });
        setForm((prev) => ({
          ...prev,
          name: detail.character_name || prev.name,
          world_name: detail.world_name || prev.world_name,
        }));
        if (detail.title) setSessionTitle(detail.title);
        setGmEnabled(detail.gm_enabled);
        if (detail.current_location) setCurrentLocation(detail.current_location);
        if (detail.time_of_day) setTimeOfDay(detail.time_of_day);

        const restored: ChatMessage[] = turnsRaw.map((t) => ({
          id: `${t.turn_index}`,
          role: (t.role === "user" ? "user" : t.turn_type === "gm_narration" || t.turn_type === "gm_event" ? "narrator" : "assistant") as ChatMessage["role"],
          content: t.content,
          messageType: (t.turn_type === "gm_narration" ? "pre_narration" : t.turn_type === "gm_event" ? "event" : "chat") as ChatMessage["messageType"],
        }));
        setChatMessages(restored);
        setSessionResumed(true);
        setStatusText(`Chronicle resumed (${detail.gm_enabled ? "GM Mode" : "Standard"}). ${detail.turn_count} turns recorded.`);

        // Load memory separately — may be slow if it needs to backfill summaries.
        try {
          setStatusText("Updating memory scrolls…");
          // Guarded by the `if (!routeSessionId) return` at the top of this effect.
          await refreshMemory(routeSessionId!);
          setStatusText(`Chronicle resumed (${detail.gm_enabled ? "GM Mode" : "Standard"}). ${detail.turn_count} turns recorded.`);
        } catch {
          setStatusText("Chronicle loaded. Memory is still syncing…");
        }
      } catch (err) {
        setStatusText(err instanceof Error ? err.message : "Failed to load chronicle.");
      } finally {
        setIsBusy(false);
      }
    }

    void resumeSession();
  }, [routeSessionId]);

  // Apply template defaults only when not resuming an existing session
  useEffect(() => {
    if (sessionResumed) return;
    const template = allTemplates.find((item) => item.id === selectedTemplateId) || allTemplates[0];
    setForm({ ...template.characterLoad });
    setSessionTitle(template.sessionTitle);
    setChatInput(template.starterUserPrompt);
    setCurrentLocation(template.startingLocation || "");
    localStorage.setItem(storageKeys.selectedTemplate, template.id);
  }, [selectedTemplateId, allTemplates, sessionResumed]);

  useEffect(() => {
    const poll = async () => {
      try {
        const nextHealth = await api<Health>("/health");
        setHealth(nextHealth);
      } catch {
        setHealth({ status: "error", database: "error", mode: "unknown" });
      }
    };

    void poll();
    const handle = window.setInterval(() => void poll(), 15000);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    localStorage.setItem(storageKeys.characterCardId, ids.characterCardId);
    localStorage.setItem(storageKeys.worldStateId, ids.worldStateId);
    localStorage.setItem(storageKeys.sessionTitle, sessionTitle);
    localStorage.setItem(storageKeys.gmEnabled, String(gmEnabled));
  }, [ids, sessionTitle, gmEnabled]);

  async function refreshMemory(sessionId: string) {
    const nextMemory = await api<SessionMemory>(`/session/${sessionId}/memory`);
    setMemory(nextMemory);
    // World-state ledger refresh — best-effort; ships dark behind a flag and
    // returns an empty version 0 when disabled, so failures shouldn't disrupt.
    try {
      const ledger = await api<WorldStateLedger>(`/session/${sessionId}/world-state`);
      setWorldState(ledger);
    } catch {
      // ignore — the Codex panel simply shows its empty state
    }
  }

  async function handleLoadCharacter(event: FormEvent) {
    event.preventDefault();
    setIsBusy(true);
    setStatusText("Loading character and world...");
    try {
      const payload = await withUiSpan(
        "ui.load_character",
        { "rpg.character_name": form.name, "rpg.world_name": form.world_name },
        () =>
          api<{
            character_card_id: string;
            world_state_id: string;
            character_name: string;
            world_name: string;
          }>("/character/load", {
            method: "POST",
            body: JSON.stringify(form),
          }),
      );
      setIds((current) => ({
        ...current,
        characterCardId: payload.character_card_id,
        worldStateId: payload.world_state_id,
      }));
      setStatusText(`Loaded ${payload.character_name} in ${payload.world_name}.`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "Failed to load character.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleStartSession() {
    if (!ids.characterCardId) {
      setStatusText("Load a character first.");
      return;
    }
    setIsBusy(true);
    setStatusText("Starting session...");
    try {
      const payload = await withUiSpan(
        "ui.new_chronicle",
        { "rpg.character_card_id": ids.characterCardId, "rpg.gm_enabled": gmEnabled },
        () =>
          api<{
            session_id: string;
            turn_count: number;
            gm_enabled: boolean;
            current_location: string | null;
            time_of_day: string | null;
          }>("/session/init", {
            method: "POST",
            body: JSON.stringify({
              character_card_id: ids.characterCardId,
              world_state_id: ids.worldStateId || null,
              title: sessionTitle || null,
              gm_enabled: gmEnabled,
              current_location: currentLocation || null,
              time_of_day: timeOfDay || null,
            }),
          }),
      );
      setIds((current) => ({ ...current, sessionId: payload.session_id }));
      setChatMessages([]);
      setRetrievedMemories([]);
      setContinuityIssues([]);
      setLastEvent(null);
      setWorldState(null);
      await refreshMemory(payload.session_id);
      const modeLabel = gmEnabled ? "GM Mode" : "Standard";
      setStatusText(`Session ready (${modeLabel}). Turn count: ${payload.turn_count}.`);
      navigate(`/chronicle/${payload.session_id}`, { replace: true });
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "Failed to start session.");
    } finally {
      setIsBusy(false);
    }
  }

  function handleSendChat() {
    void sendChat({
      sessionId: ids.sessionId,
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

  const selectedTemplate =
    allTemplates.find((item) => item.id === selectedTemplateId) || allTemplates[0];

  // Wizard phase: "codex" = character setup, "chronicle" = active play
  const phase = ids.sessionId ? "chronicle" : "codex";

  return (
    <div className="shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />
      <header className="masthead">
        <div>
          <p className="eyebrow">Arcane Chronicle</p>
          {phase === "codex" ? (
            <>
              <h1>
                <button type="button" className="title-home" onClick={() => navigate("/")} title="Return to the Vault">
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
                <button type="button" className="title-home" onClick={() => navigate("/")} title="Return to the Vault">
                  ✦ Live Chronicle
                </button>
              </h1>
              <p className="lede">
                Your story unfolds — speak and the world responds.
              </p>
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

      {phase === "codex" && (
        <main className="codex-stage">
          <CharacterPanel
            templates={allTemplates}
            form={form}
            setForm={setForm}
            selectedTemplateId={selectedTemplateId}
            setSelectedTemplateId={setSelectedTemplateId}
            sessionTitle={sessionTitle}
            setSessionTitle={setSessionTitle}
            isBusy={isBusy}
            gmEnabled={gmEnabled}
            setGmEnabled={setGmEnabled}
            currentLocation={currentLocation}
            setCurrentLocation={setCurrentLocation}
            timeOfDay={timeOfDay}
            setTimeOfDay={setTimeOfDay}
            onLoadCharacter={handleLoadCharacter}
            onStartSession={handleStartSession}
            onLoadOpening={() => setChatInput(selectedTemplate.starterUserPrompt)}
          />
        </main>
      )}

      {phase === "chronicle" && (
        <>
          <div className="chronicle-summary-bar">
            <div className="summary-item">
              <span className="meta-label">Protagonist</span>
              <strong>{form.name || "—"}</strong>
            </div>
            <div className="summary-item">
              <span className="meta-label">Realm</span>
              <strong>{form.world_name || "—"}</strong>
            </div>
            {gmEnabled && (
              <div className="summary-item">
                <span className="meta-label">Location</span>
                <strong>{currentLocation || "—"}</strong>
              </div>
            )}
            <div className="summary-item">
              <span className="meta-label">Mode</span>
              <strong>{gmEnabled ? "✧ Game Master" : "Standard"}</strong>
            </div>
          </div>
          <main className="dashboard dashboard-chronicle">
            <ChatPanel
              chatMessages={chatMessages}
              chatInput={chatInput}
              setChatInput={setChatInput}
              isBusy={isBusy}
              sessionId={ids.sessionId}
              characterName={form.name}
              worldName={form.world_name}
              gmEnabled={gmEnabled}
              statusText={statusText}
              onSendChat={handleSendChat}
            />
            <div className="panel-stack">
              <CodexPanel worldState={worldState} />
              <MemoryPanel
                retrievedMemories={retrievedMemories}
                continuityIssues={continuityIssues}
                memory={memory}
              />
            </div>
          </main>
        </>
      )}
    </div>
  );
}
