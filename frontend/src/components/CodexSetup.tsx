import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { storageKeys } from "../api";
import { useHealth } from "../hooks/useHealth";
import { useLoadCharacter, useStartSession } from "../hooks/useSessionMutations";
import { loadAllTemplates } from "../loadTemplates";
import { templates as baseTemplates, type RoleplayTemplate } from "../templates";
import type { CharacterLoadPayload } from "../types";
import { CharacterPanel } from "./CharacterPanel";

type Props = {
  /** Called with the new session id and the starter prompt to seed the chat box. */
  onStarted: (sessionId: string, starterPrompt: string) => void;
};

/** null = the user never touched this toggle (no stored choice). */
function readStoredToggle(key: string): boolean | null {
  const raw = localStorage.getItem(key);
  return raw === null ? null : raw === "true";
}

/**
 * Character/world setup. Owns the state that survives template switches
 * (selected template, GM mode, time of day, loaded ids); the per-template
 * fields live in {@link CodexForm}, which is remounted via `key` when the
 * resolved template changes — so picking a template (or async-loading an extra
 * one) re-seeds the form without a set-state-in-effect.
 */
export function CodexSetup({ onStarted }: Props) {
  // placeholderData (not initialData) shows the built-in templates immediately
  // while still fetching the extra ones — initialData + staleTime:Infinity would
  // treat the seed as fresh and never load templates-extra.json.
  const { data: templates = baseTemplates } = useQuery({
    queryKey: ["templates"],
    queryFn: loadAllTemplates,
    placeholderData: baseTemplates,
    staleTime: Infinity,
  });

  const [selectedTemplateId, setSelectedTemplateId] = useState(
    () => localStorage.getItem(storageKeys.selectedTemplate) || baseTemplates[0].id,
  );
  // Toggle defaults: an explicit user choice (persisted in localStorage) wins;
  // otherwise seed from the backend's global defaults via /health, which come
  // from docker compose (the dev override turns everything on).
  const health = useHealth();
  const [gmChoice, setGmChoice] = useState<boolean | null>(() => readStoredToggle(storageKeys.gmEnabled));
  const [suggestionsChoice, setSuggestionsChoice] = useState<boolean | null>(() =>
    readStoredToggle(storageKeys.suggestionsEnabled),
  );
  const [worldStateChoice, setWorldStateChoice] = useState<boolean | null>(() =>
    readStoredToggle(storageKeys.worldStateEnabled),
  );
  const [questsChoice, setQuestsChoice] = useState<boolean | null>(() =>
    readStoredToggle(storageKeys.questsEnabled),
  );
  const gmEnabled = gmChoice ?? health?.gm_enabled ?? false;
  const suggestionsEnabled = suggestionsChoice ?? health?.suggestions_enabled ?? false;
  const worldStateEnabled = worldStateChoice ?? health?.world_state_enabled ?? false;
  const questsEnabled = questsChoice ?? health?.quests_enabled ?? false;
  const [timeOfDay, setTimeOfDay] = useState("morning");
  const [ids, setIds] = useState(() => ({
    characterCardId: localStorage.getItem(storageKeys.characterCardId) || "",
    worldStateId: localStorage.getItem(storageKeys.worldStateId) || "",
  }));

  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId) || templates[0];

  function handleSelectTemplate(id: string) {
    setSelectedTemplateId(id);
    localStorage.setItem(storageKeys.selectedTemplate, id);
  }

  function handleSetGmEnabled(value: boolean) {
    setGmChoice(value);
    localStorage.setItem(storageKeys.gmEnabled, String(value));
  }

  function handleSetSuggestionsEnabled(value: boolean) {
    setSuggestionsChoice(value);
    localStorage.setItem(storageKeys.suggestionsEnabled, String(value));
  }

  function handleSetWorldStateEnabled(value: boolean) {
    setWorldStateChoice(value);
    localStorage.setItem(storageKeys.worldStateEnabled, String(value));
  }

  function handleSetQuestsEnabled(value: boolean) {
    setQuestsChoice(value);
    localStorage.setItem(storageKeys.questsEnabled, String(value));
  }

  return (
    <CodexForm
      key={selectedTemplate.id}
      template={selectedTemplate}
      templates={templates}
      selectedTemplateId={selectedTemplateId}
      onSelectTemplate={handleSelectTemplate}
      gmEnabled={gmEnabled}
      setGmEnabled={handleSetGmEnabled}
      suggestionsEnabled={suggestionsEnabled}
      setSuggestionsEnabled={handleSetSuggestionsEnabled}
      worldStateEnabled={worldStateEnabled}
      setWorldStateEnabled={handleSetWorldStateEnabled}
      questsEnabled={questsEnabled}
      setQuestsEnabled={handleSetQuestsEnabled}
      toggleChoices={{
        gm: gmChoice,
        suggestions: suggestionsChoice,
        worldState: worldStateChoice,
        quests: questsChoice,
      }}
      timeOfDay={timeOfDay}
      setTimeOfDay={setTimeOfDay}
      ids={ids}
      setIds={setIds}
      onStarted={onStarted}
    />
  );
}

type CodexFormProps = {
  template: RoleplayTemplate;
  templates: RoleplayTemplate[];
  selectedTemplateId: string;
  onSelectTemplate: (id: string) => void;
  gmEnabled: boolean;
  setGmEnabled: (v: boolean) => void;
  suggestionsEnabled: boolean;
  setSuggestionsEnabled: (v: boolean) => void;
  worldStateEnabled: boolean;
  setWorldStateEnabled: (v: boolean) => void;
  questsEnabled: boolean;
  setQuestsEnabled: (v: boolean) => void;
  /** Raw toggle choices: null = user never touched it (inherit the global). */
  toggleChoices: {
    gm: boolean | null;
    suggestions: boolean | null;
    worldState: boolean | null;
    quests: boolean | null;
  };
  timeOfDay: string;
  setTimeOfDay: (v: string) => void;
  ids: { characterCardId: string; worldStateId: string };
  setIds: (ids: { characterCardId: string; worldStateId: string }) => void;
  onStarted: (sessionId: string, starterPrompt: string) => void;
};

function CodexForm({
  template,
  templates,
  selectedTemplateId,
  onSelectTemplate,
  gmEnabled,
  setGmEnabled,
  suggestionsEnabled,
  setSuggestionsEnabled,
  worldStateEnabled,
  setWorldStateEnabled,
  questsEnabled,
  setQuestsEnabled,
  toggleChoices,
  timeOfDay,
  setTimeOfDay,
  ids,
  setIds,
  onStarted,
}: CodexFormProps) {
  // Seeded from the template prop; reset on template switch via the parent's key.
  const [form, setForm] = useState<CharacterLoadPayload>(() => ({ ...template.characterLoad }));
  const [sessionTitle, setSessionTitle] = useState(template.sessionTitle);
  const [starterPrompt, setStarterPrompt] = useState(template.starterUserPrompt);
  const [currentLocation, setCurrentLocation] = useState(template.startingLocation || "");
  const [statusText, setStatusText] = useState("Ready.");

  const loadCharacter = useLoadCharacter();
  const startSession = useStartSession();
  const isBusy = loadCharacter.isPending || startSession.isPending;

  async function handleLoadCharacter(event: FormEvent) {
    event.preventDefault();
    setStatusText("Loading character and world...");
    try {
      const payload = await loadCharacter.mutateAsync(form);
      const next = { characterCardId: payload.character_card_id, worldStateId: payload.world_state_id };
      setIds(next);
      localStorage.setItem(storageKeys.characterCardId, next.characterCardId);
      localStorage.setItem(storageKeys.worldStateId, next.worldStateId);
      setStatusText(`Loaded ${payload.character_name} in ${payload.world_name}.`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "Failed to load character.");
    }
  }

  async function handleStartSession() {
    if (!ids.characterCardId) {
      setStatusText("Load a character first.");
      return;
    }
    setStatusText("Starting session...");
    try {
      const payload = await startSession.mutateAsync({
        character_card_id: ids.characterCardId,
        world_state_id: ids.worldStateId || null,
        title: sessionTitle || null,
        current_location: currentLocation || null,
        time_of_day: timeOfDay || null,
        // Send the raw choices, not the resolved booleans: null = the user
        // never touched the toggle, so the session inherits the global
        // default (and follows it if the defaults flip later).
        gm_enabled: toggleChoices.gm,
        suggestions_enabled: toggleChoices.suggestions,
        world_state_enabled: toggleChoices.worldState,
        quests_enabled: toggleChoices.quests,
      });
      localStorage.setItem(storageKeys.sessionTitle, sessionTitle);
      onStarted(payload.session_id, starterPrompt);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "Failed to start session.");
    }
  }

  return (
    <main className="codex-stage">
      <CharacterPanel
        templates={templates}
        form={form}
        setForm={setForm}
        selectedTemplateId={selectedTemplateId}
        setSelectedTemplateId={onSelectTemplate}
        sessionTitle={sessionTitle}
        setSessionTitle={setSessionTitle}
        isBusy={isBusy}
        gmEnabled={gmEnabled}
        setGmEnabled={setGmEnabled}
        suggestionsEnabled={suggestionsEnabled}
        setSuggestionsEnabled={setSuggestionsEnabled}
        worldStateEnabled={worldStateEnabled}
        setWorldStateEnabled={setWorldStateEnabled}
        questsEnabled={questsEnabled}
        setQuestsEnabled={setQuestsEnabled}
        currentLocation={currentLocation}
        setCurrentLocation={setCurrentLocation}
        timeOfDay={timeOfDay}
        setTimeOfDay={setTimeOfDay}
        onLoadCharacter={handleLoadCharacter}
        onStartSession={handleStartSession}
        onLoadOpening={() => setStarterPrompt(template.starterUserPrompt)}
      />
      <p className="muted codex-status" role="status">{statusText}</p>
    </main>
  );
}
