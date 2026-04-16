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
  role: "user" | "assistant";
  content: string;
};

const storageKeys = {
  characterCardId: "small-rpg:character-card-id",
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
  }, [ids, sessionTitle]);

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
      }>("/session/init", {
        method: "POST",
        body: JSON.stringify({
          character_card_id: ids.characterCardId,
          world_state_id: ids.worldStateId || null,
          title: sessionTitle || null,
        }),
      });
      setIds((current) => ({ ...current, sessionId: payload.session_id }));
      setChatMessages([]);
      setRetrievedMemories([]);
      setContinuityIssues([]);
      await refreshMemory(payload.session_id);
      setStatusText(`Session ready. Turn count: ${payload.turn_count}.`);
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
    setStatusText("Generating in-character reply...");

    try {
      const payload = await api<{
        reply: string;
        continuity_issues: string[];
        retrieved_memories: RetrievedMemory[];
      }>("/chat", {
        method: "POST",
        body: JSON.stringify({
          session_id: ids.sessionId,
          user_message: currentInput,
        }),
      });

      setChatMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: payload.reply,
        },
      ]);
      setRetrievedMemories(payload.retrieved_memories);
      setContinuityIssues(payload.continuity_issues);
      await refreshMemory(ids.sessionId);
      setStatusText("Reply generated.");
    } catch (error) {
      setChatMessages((current) => current.filter((item) => item.id !== userMessage.id));
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
          <p className="eyebrow">Small Models Only</p>
          <h1>Roleplay Control Room</h1>
          <p className="lede">
            Template-driven character setup, live in-character chat, retrieval visibility, and long-term memory inspection in one console.
          </p>
        </div>
        <div className="status-strip">
          <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}>API {health?.status || "..."}</div>
          <div className={`pill ${health?.database === "ok" ? "ok" : "warn"}`}>DB {health?.database || "..."}</div>
          <div className="pill neutral">Ollama-first</div>
          <div className="pill neutral">pnpm + Vite</div>
        </div>
      </header>

      <main className="dashboard">
        <section className="panel panel-left">
          <div className="panel-header">
            <p className="eyebrow">Templates</p>
            <h2>Starting Cast</h2>
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
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label>
                Session Title
                <input value={sessionTitle} onChange={(event) => setSessionTitle(event.target.value)} />
              </label>
            </div>

            <label>
              Character Description
              <textarea
                rows={5}
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>

            <label>
              Character Hard Rules
              <textarea
                rows={5}
                value={listToText(form.hard_rules)}
                onChange={(event) => setForm((current) => ({ ...current, hard_rules: textToList(event.target.value) }))}
              />
            </label>

            <label>
              Style Guide
              <textarea
                rows={3}
                value={form.style_guide}
                onChange={(event) => setForm((current) => ({ ...current, style_guide: event.target.value }))}
              />
            </label>

            <div className="form-row">
              <label>
                World Name
                <input
                  value={form.world_name}
                  onChange={(event) => setForm((current) => ({ ...current, world_name: event.target.value }))}
                />
              </label>
              <label>
                Template Difficulty
                <input value={selectedTemplate.difficulty} disabled />
              </label>
            </div>

            <label>
              World Description
              <textarea
                rows={4}
                value={form.world_description}
                onChange={(event) => setForm((current) => ({ ...current, world_description: event.target.value }))}
              />
            </label>

            <label>
              World Canon
              <textarea
                rows={4}
                value={form.world_canon}
                onChange={(event) => setForm((current) => ({ ...current, world_canon: event.target.value }))}
              />
            </label>

            <label>
              World Hard Rules
              <textarea
                rows={4}
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

            <div className="button-row">
              <button className="btn btn-primary" type="submit" disabled={isBusy}>
                Load Character
              </button>
              <button className="btn btn-secondary" type="button" disabled={isBusy} onClick={handleStartSession}>
                Start Session
              </button>
              <button className="btn btn-secondary" type="button" onClick={() => setChatInput(selectedTemplate.starterUserPrompt)}>
                Use Starter Prompt
              </button>
            </div>
          </form>
        </section>

        <section className="panel panel-center">
          <div className="panel-header">
            <p className="eyebrow">Live Scene</p>
            <h2>Transcript</h2>
          </div>

          <div className="session-meta">
            <div>
              <span className="meta-label">Character</span>
              <strong>{form.name}</strong>
            </div>
            <div>
              <span className="meta-label">Session</span>
              <strong>{ids.sessionId || "Not started"}</strong>
            </div>
            <div>
              <span className="meta-label">World</span>
              <strong>{form.world_name}</strong>
            </div>
          </div>

          <div className="chat-log">
            {chatMessages.length === 0 ? (
              <div className="empty-state">
                <p>No turns yet.</p>
                <span>Load a template, start a session, then send the opener.</span>
              </div>
            ) : (
              chatMessages.map((message) => (
                <article key={message.id} className={`message message-${message.role}`}>
                  <div className="message-role">{message.role === "user" ? "You" : form.name}</div>
                  <p>{message.content}</p>
                </article>
              ))
            )}
          </div>

          <div className="composer">
            <textarea
              rows={4}
              placeholder="Write the next turn..."
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
            />
            <div className="composer-actions">
              <div className="status-note">{statusText}</div>
              <button className="btn btn-primary" type="button" disabled={isBusy || !ids.sessionId} onClick={handleSendChat}>
                {isBusy ? "Working..." : "Send Turn"}
              </button>
            </div>
          </div>
        </section>

        <section className="panel panel-right">
          <div className="panel-header">
            <p className="eyebrow">Memory + Debug</p>
            <h2>Inspector</h2>
          </div>

          <div className="stack">
            <div className="subpanel">
              <h3>Retrieved This Turn</h3>
              {retrievedMemories.length === 0 ? (
                <p className="muted">No retrieval results yet.</p>
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
              <h3>Continuity Notes</h3>
              {continuityIssues.length === 0 ? (
                <p className="muted">No continuity corrections on the latest reply.</p>
              ) : (
                continuityIssues.map((issue) => (
                  <div key={issue} className="issue-card">
                    {issue}
                  </div>
                ))
              )}
            </div>

            <div className="subpanel">
              <h3>Long-Term Facts</h3>
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
                <p className="muted">Facts appear after a few turns.</p>
              )}
            </div>

            <div className="subpanel">
              <h3>Episode Summaries</h3>
              {memory?.episode_summaries.length ? (
                memory.episode_summaries.slice(0, 4).map((summary) => (
                  <div key={summary.id} className="memory-card">
                    <div className="memory-topline">
                      <span>
                        turns {summary.start_turn_index}-{summary.end_turn_index}
                      </span>
                      <span>{summary.importance.toFixed(2)}</span>
                    </div>
                    <p>{summary.content}</p>
                  </div>
                ))
              ) : (
                <p className="muted">No summaries yet.</p>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
