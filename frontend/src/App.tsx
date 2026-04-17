import { FormEvent, useEffect, useState } from "react";

import { templates } from "./templates";

type Health = {
  status: string;
  database: string;
};

type CharacterLoadPayload = {
  name: string;
  description: string;
  hard_rules: string[];
  style_guide: string;
  world_name: string;
  world_description: string;
  world_canon: string;
  world_hard_rules: string[];
};

type SessionMemory = {
  session_id: string;
  facts: Array<{ id: string; content: string; importance: number; created_at: string }>;
  episode_summaries: Array<{
    id: string;
    content: string;
    importance: number;
    start_turn_index: number;
    end_turn_index: number;
    created_at: string;
  }>;
  relationships: Array<{
    id: string;
    source_entity: string;
    target_entity: string;
    status: string;
    notes: string | null;
    importance: number;
    updated_at: string;
  }>;
};

type RetrievedMemory = {
  id: string;
  kind: string;
  content: string;
  weighted_score: number;
  semantic_score: number;
  recency_score: number;
  importance: number;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "narrator";
  content: string;
  messageType?: "chat" | "pre_narration" | "post_narration" | "event";
};

// GM Mode Types
type GMEvent = {
  event_type: string;
  urgency: string;
  description: string;
  npcs_involved: string[];
};

type GMChatResponse = {
  session_id: string;
  pre_narration: string | null;
  character_reply: string;
  post_narration: string | null;
  event: GMEvent | null;
  continuity_applied: boolean;
  continuity_issues: string[];
  retrieved_memories: RetrievedMemory[];
};

const storageKeys = {
  characterCardId: "small-rpg:character-card-id",
  gmEnabled: "small-rpg:gm-enabled",
  worldStateId: "small-rpg:world-state-id",
  sessionId: "small-rpg:session-id",
  sessionTitle: "small-rpg:session-title",
  selectedTemplate: "small-rpg:selected-template",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || "Request failed");
  }

  return response.json() as Promise<T>;
}

function listToText(items: string[]): string {
  return items.join("\n");
}

function textToList(text: string): string[] {
  return text
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function createInitialForm(): CharacterLoadPayload {
  const firstTemplate = templates[0];
  return { ...firstTemplate.characterLoad };
}

export default function App() {
  const [selectedTemplateId, setSelectedTemplateId] = useState(
    localStorage.getItem(storageKeys.selectedTemplate) || templates[0].id,
  );
  const [form, setForm] = useState<CharacterLoadPayload>(createInitialForm);
  const [health, setHealth] = useState<Health | null>(null);
  const [statusText, setStatusText] = useState("Ready.");
  const [isBusy, setIsBusy] = useState(false);
  const [sessionTitle, setSessionTitle] = useState(localStorage.getItem(storageKeys.sessionTitle) || templates[0].sessionTitle);
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
    const template = templates.find((item) => item.id === selectedTemplateId) || templates[0];
    setForm({ ...template.characterLoad });
    setSessionTitle(template.sessionTitle);
    setChatInput(template.starterUserPrompt);
    localStorage.setItem(storageKeys.selectedTemplate, template.id);
  }, [selectedTemplateId]);

  useEffect(() => {
    const poll = async () => {
      try {
        const nextHealth = await api<Health>("/health");
        setHealth(nextHealth);
      } catch {
        setHealth({ status: "error", database: "error" });
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

  async function handleSendChat() {
    if (!ids.sessionId) {
      setStatusText("Start a session first.");
      return;
    }
    if (!chatInput.trim()) {
      setStatusText("Write a message first.");
      return;
    }

    const currentInput = chatInput.trim();
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: currentInput,
    };

    setChatMessages((current) => [...current, userMessage]);
    setChatInput("");
    setIsBusy(true);

    // Use GM mode endpoint if enabled
    if (gmEnabled) {
      setStatusText("The Game Master weaves the tale...");
      try {
        const response = await api<GMChatResponse>("/gm/chat", {
          method: "POST",
          body: JSON.stringify({
            session_id: ids.sessionId,
            user_message: currentInput,
            gm_mode: true,
            location: currentLocation || null,
            time_of_day: timeOfDay || null,
          }),
        });

        const newMessages: ChatMessage[] = [];

        // Add pre-narration from GM
        if (response.pre_narration) {
          newMessages.push({
            id: crypto.randomUUID(),
            role: "narrator",
            content: response.pre_narration,
            messageType: "pre_narration",
          });
        }

        // Add character reply
        newMessages.push({
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.character_reply,
          messageType: "chat",
        });

        // Add post-narration/event from GM
        if (response.post_narration) {
          newMessages.push({
            id: crypto.randomUUID(),
            role: "narrator",
            content: response.post_narration,
            messageType: response.event ? "event" : "post_narration",
          });
        }

        setChatMessages((current) => [...current, ...newMessages]);
        setRetrievedMemories(response.retrieved_memories);
        setContinuityIssues(response.continuity_issues);
        if (response.event) {
          setLastEvent(response.event);
        }
        await refreshMemory(ids.sessionId);
        setStatusText(response.event ? `Event triggered: ${response.event.event_type}` : "The tale unfolds...");
      } catch (error) {
        setChatMessages((current) => current.filter((item) => item.id !== userMessage.id));
        setChatInput(currentInput);
        setStatusText(error instanceof Error ? error.message : "GM chat request failed.");
      } finally {
        setIsBusy(false);
      }
      return;
    }

    // Standard streaming chat (non-GM mode)
    const assistantMessageId = crypto.randomUUID();
    setChatMessages((current) => [
      ...current,
      { id: assistantMessageId, role: "assistant", content: "" },
    ]);
    setStatusText("Generating in-character reply...");

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: ids.sessionId,
          user_message: currentInput,
        }),
      });

      if (!response.ok) {
        throw new Error(response.statusText || "Stream request failed");
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Failed to get response reader");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6);
          if (!jsonStr.trim()) continue;

          try {
            const event = JSON.parse(jsonStr);

            if (event.type === "chunk") {
              setChatMessages((current) =>
                current.map((msg) =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: msg.content + event.content }
                    : msg
                )
              );
            } else if (event.type === "memories") {
              setRetrievedMemories(event.memories);
            } else if (event.type === "error") {
              throw new Error(event.error);
            } else if (event.type === "done") {
              await refreshMemory(ids.sessionId);
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      }

      setContinuityIssues([]);
      setStatusText("Reply generated.");
    } catch (error) {
      setChatMessages((current) =>
        current.filter((item) => item.id !== userMessage.id && item.id !== assistantMessageId)
      );
      setChatInput(currentInput);
      setStatusText(error instanceof Error ? error.message : "Chat request failed.");
    } finally {
      setIsBusy(false);
    }
  }

  const selectedTemplate = templates.find((item) => item.id === selectedTemplateId) || templates[0];

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
          <div className="pill neutral">Local Models</div>
          <div className="pill neutral">Ollama</div>
        </div>
      </header>

      <main className="dashboard">
        <section className="panel panel-left">
          <div className="panel-header">
            <p className="eyebrow">Character Codex</p>
            <h2>Choose Your Path</h2>
          </div>
          <div className="template-grid">
            {templates.map((template) => (
              <button
                key={template.id}
                type="button"
                className={`template-card ${template.id === selectedTemplateId ? "active" : ""}`}
                onClick={() => setSelectedTemplateId(template.id)}
              >
                <span className="template-genre">{template.genre}</span>
                <strong>{template.label}</strong>
                <span>{template.tone}</span>
              </button>
            ))}
          </div>

          <form className="editor-form" onSubmit={handleLoadCharacter}>
            <div className="form-row">
              <label>
                Character Name
                <input
                  value={form.name}
                  placeholder="Enter name..."
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label>
                Chronicle Title
                <input value={sessionTitle} placeholder="Name this session..." onChange={(event) => setSessionTitle(event.target.value)} />
              </label>
            </div>

            <label>
              Character Lore
              <textarea
                rows={5}
                placeholder="Describe their history, personality, and motivations..."
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>

            <label>
              Sacred Laws
              <textarea
                rows={5}
                placeholder="Rules the character must never break..."
                value={listToText(form.hard_rules)}
                onChange={(event) => setForm((current) => ({ ...current, hard_rules: textToList(event.target.value) }))}
              />
            </label>

            <label>
              Voice &amp; Style
              <textarea
                rows={3}
                placeholder="How they speak and carry themselves..."
                value={form.style_guide}
                onChange={(event) => setForm((current) => ({ ...current, style_guide: event.target.value }))}
              />
            </label>

            <div className="form-row">
              <label>
                Realm Name
                <input
                  placeholder="Name of the world..."
                  value={form.world_name}
                  onChange={(event) => setForm((current) => ({ ...current, world_name: event.target.value }))}
                />
              </label>
              <label>
                Challenge Rating
                <input value={selectedTemplate.difficulty} disabled />
              </label>
            </div>

            <label>
              Realm Description
              <textarea
                rows={4}
                placeholder="Paint the world in words..."
                value={form.world_description}
                onChange={(event) => setForm((current) => ({ ...current, world_description: event.target.value }))}
              />
            </label>

            <label>
              Established Canon
              <textarea
                rows={4}
                placeholder="Known truths of this world..."
                value={form.world_canon}
                onChange={(event) => setForm((current) => ({ ...current, world_canon: event.target.value }))}
              />
            </label>

            <label>
              World Laws
              <textarea
                rows={4}
                placeholder="Immutable rules of reality..."
                value={listToText(form.world_hard_rules)}
                onChange={(event) => setForm((current) => ({ ...current, world_hard_rules: textToList(event.target.value) }))}
              />
            </label>

            <div className="tag-row">
              {selectedTemplate.tags.map((tag) => (
                <span key={tag} className="tag">
                  {tag}
                </span>
              ))}
            </div>

            {/* GM Mode Controls */}
            <div className="gm-controls">
              <label className="gm-toggle">
                <input
                  type="checkbox"
                  checked={gmEnabled}
                  onChange={(e) => setGmEnabled(e.target.checked)}
                />
                <span className="toggle-label">✧ Game Master Mode</span>
                <span className="toggle-hint">{gmEnabled ? "World narration & events active" : "Character-only mode"}</span>
              </label>

              {gmEnabled && (
                <div className="gm-settings">
                  <div className="form-row">
                    <label>
                      Current Location
                      <input
                        placeholder="Where in the world..."
                        value={currentLocation}
                        onChange={(e) => setCurrentLocation(e.target.value)}
                      />
                    </label>
                    <label>
                      Time of Day
                      <select value={timeOfDay} onChange={(e) => setTimeOfDay(e.target.value)}>
                        <option value="dawn">Dawn</option>
                        <option value="morning">Morning</option>
                        <option value="midday">Midday</option>
                        <option value="afternoon">Afternoon</option>
                        <option value="dusk">Dusk</option>
                        <option value="evening">Evening</option>
                        <option value="night">Night</option>
                        <option value="midnight">Midnight</option>
                      </select>
                    </label>
                  </div>
                </div>
              )}
            </div>

            <div className="button-row">
              <button className="btn btn-primary" type="submit" disabled={isBusy}>
                ⚔ Summon Character
              </button>
              <button className="btn btn-secondary" type="button" disabled={isBusy} onClick={handleStartSession}>
                ✦ Begin Chronicle
              </button>
              <button className="btn btn-secondary" type="button" onClick={() => setChatInput(selectedTemplate.starterUserPrompt)}>
                ↯ Load Opening
              </button>
            </div>
          </form>
        </section>

        <section className="panel panel-center">
          <div className="panel-header">
            <p className="eyebrow">Live Chronicle</p>
            <h2>The Unfolding Tale</h2>
          </div>

          <div className="session-meta">
            <div>
              <span className="meta-label">Protagonist</span>
              <strong>{form.name || "—"}</strong>
            </div>
            <div>
              <span className="meta-label">Chronicle</span>
              <strong>{ids.sessionId ? `#${ids.sessionId.slice(0, 8)}` : "Awaiting"}</strong>
            </div>
            <div>
              <span className="meta-label">Realm</span>
              <strong>{form.world_name || "—"}</strong>
            </div>
            {gmEnabled && (
              <div>
                <span className="meta-label">Mode</span>
                <strong className="gm-badge">✧ GM</strong>
              </div>
            )}
          </div>

          <div className="chat-log">
            {chatMessages.length === 0 ? (
              <div className="empty-state">
                <p>The pages await your tale</p>
                <span>Choose a character template, begin a chronicle, then speak your opening words</span>
              </div>
            ) : (
              chatMessages.map((message) => (
                <article
                  key={message.id}
                  className={`message message-${message.role}${message.messageType ? ` message-type-${message.messageType}` : ""}`}
                >
                  <div className="message-role">
                    {message.role === "user"
                      ? "You"
                      : message.role === "narrator"
                        ? "✧ Game Master"
                        : form.name}
                  </div>
                  <p>{message.content}</p>
                </article>
              ))
            )}
          </div>

          <div className="composer">
            <textarea
              rows={4}
              placeholder="Inscribe your next action or words..."
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
            />
            <div className="composer-actions">
              <div className="status-note">{statusText}</div>
              <button className="btn btn-primary" type="button" disabled={isBusy || !ids.sessionId} onClick={handleSendChat}>
                {isBusy ? "✦ Weaving..." : "▶ Send Turn"}
              </button>
            </div>
          </div>
        </section>

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
      </main>
    </div>
  );
}
