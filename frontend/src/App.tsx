import { FormEvent, useEffect, useState } from "react";

import { templates as baseTemplates } from "./templates";
import { loadAllTemplates } from "./loadTemplates";
import { api, storageKeys, createInitialForm } from "./api";
import { sendChat } from "./chat";
import { CharacterPanel } from "./components/CharacterPanel";
import { ChatPanel } from "./components/ChatPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import type {
  CharacterLoadPayload,
  ChatMessage,
  GMEvent,
  Health,
  RetrievedMemory,
  SessionMemory,
} from "./types";

export default function App() {
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
  const [ids, setIds] = useState({
    characterCardId: localStorage.getItem(storageKeys.characterCardId) || "",
    worldStateId: localStorage.getItem(storageKeys.worldStateId) || "",
    sessionId: localStorage.getItem(storageKeys.sessionId) || "",
  });

  // GM Mode state
  const [gmEnabled, setGmEnabled] = useState(localStorage.getItem(storageKeys.gmEnabled) === "true");
  const [currentLocation, setCurrentLocation] = useState("");
  const [timeOfDay, setTimeOfDay] = useState("morning");
  const [lastEvent, setLastEvent] = useState<GMEvent | null>(null);

  useEffect(() => {
    loadAllTemplates().then(setAllTemplates);
  }, []);

  useEffect(() => {
    const template = allTemplates.find((item) => item.id === selectedTemplateId) || allTemplates[0];
    setForm({ ...template.characterLoad });
    setSessionTitle(template.sessionTitle);
    setChatInput(template.starterUserPrompt);
    setCurrentLocation(template.startingLocation || "");
    localStorage.setItem(storageKeys.selectedTemplate, template.id);
  }, [selectedTemplateId, allTemplates]);

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
    localStorage.setItem(storageKeys.sessionId, ids.sessionId);
    localStorage.setItem(storageKeys.sessionTitle, sessionTitle);
    localStorage.setItem(storageKeys.gmEnabled, String(gmEnabled));
  }, [ids, sessionTitle, gmEnabled]);

  async function refreshMemory(sessionId: string) {
    const nextMemory = await api<SessionMemory>(`/session/${sessionId}/memory`);
    setMemory(nextMemory);
  }

  async function handleLoadCharacter(event: FormEvent) {
    event.preventDefault();
    setIsBusy(true);
    setStatusText("Loading character and world...");
    try {
      const payload = await api<{
        character_card_id: string;
        world_state_id: string;
        character_name: string;
        world_name: string;
      }>("/character/load", {
        method: "POST",
        body: JSON.stringify(form),
      });
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
      const payload = await api<{
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
      });
      setIds((current) => ({ ...current, sessionId: payload.session_id }));
      setChatMessages([]);
      setRetrievedMemories([]);
      setContinuityIssues([]);
      setLastEvent(null);
      await refreshMemory(payload.session_id);
      const modeLabel = gmEnabled ? "GM Mode" : "Standard";
      setStatusText(`Session ready (${modeLabel}). Turn count: ${payload.turn_count}.`);
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

  return (
    <div className="shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />
      <header className="masthead">
        <div>
          <p className="eyebrow">Arcane Chronicle</p>
          <h1>✦ Roleplay Session Console</h1>
          <p className="lede">
            Craft your character, weave your story, and watch memories form across the tapestry of your adventure.
          </p>
        </div>
        <div className="status-strip">
          <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}>Realm {health?.status || "..."}</div>
          <div className={`pill ${health?.database === "ok" ? "ok" : "warn"}`}>Archive {health?.database || "..."}</div>
          <div className={`pill ${health?.mode === "DEV" ? "warn" : "ok"}`}>{health?.mode || "..."}</div>
          <div className="pill neutral">Local Models</div>
          <div className="pill neutral">Ollama</div>
        </div>
      </header>

      <main className="dashboard">
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
        <MemoryPanel
          retrievedMemories={retrievedMemories}
          continuityIssues={continuityIssues}
          memory={memory}
        />
      </main>
    </div>
  );
}
