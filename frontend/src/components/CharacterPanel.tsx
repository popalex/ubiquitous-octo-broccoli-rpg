import type { FormEvent } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { RoleplayTemplate } from "../templates";
import { listToText, textToList } from "../api";
import type { CharacterLoadPayload } from "../types";
import { Button } from "./ui/Button";

type Props = {
  templates: RoleplayTemplate[];
  form: CharacterLoadPayload;
  setForm: Dispatch<SetStateAction<CharacterLoadPayload>>;
  selectedTemplateId: string;
  setSelectedTemplateId: (id: string) => void;
  sessionTitle: string;
  setSessionTitle: (t: string) => void;
  isBusy: boolean;
  gmEnabled: boolean;
  setGmEnabled: (v: boolean) => void;
  worldStateEnabled: boolean;
  setWorldStateEnabled: (v: boolean) => void;
  questsEnabled: boolean;
  setQuestsEnabled: (v: boolean) => void;
  currentLocation: string;
  setCurrentLocation: (v: string) => void;
  timeOfDay: string;
  setTimeOfDay: (v: string) => void;
  onLoadCharacter: (e: FormEvent) => void;
  onStartSession: () => void;
  onLoadOpening: () => void;
};

const desc = {
  name: "character-name-desc",
  session: "session-title-desc",
  lore: "character-lore-desc",
  laws: "sacred-laws-desc",
  voice: "voice-style-desc",
  realm: "realm-name-desc",
  realmDesc: "realm-desc-desc",
  canon: "established-canon-desc",
  worldLaws: "world-laws-desc",
  location: "current-location-desc",
};

export function CharacterPanel({
  templates,
  form,
  setForm,
  selectedTemplateId,
  setSelectedTemplateId,
  sessionTitle,
  setSessionTitle,
  isBusy,
  gmEnabled,
  setGmEnabled,
  worldStateEnabled,
  setWorldStateEnabled,
  questsEnabled,
  setQuestsEnabled,
  currentLocation,
  setCurrentLocation,
  timeOfDay,
  setTimeOfDay,
  onLoadCharacter,
  onStartSession,
  onLoadOpening,
}: Props) {
  const selectedTemplate =
    templates.find((item) => item.id === selectedTemplateId) || templates[0];

  return (
    <section className="panel codex-panel">
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

      <form className="editor-form" onSubmit={onLoadCharacter}>
        <div className="form-row">
          <label>
            Character Name
            <input
              value={form.name}
              placeholder="Enter name..."
              aria-describedby={desc.name}
              onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))}
            />
          </label>
          <span id={desc.name} className="sr-only">The name of your character</span>
          <label>
            Chronicle Title
            <input
              value={sessionTitle}
              placeholder="Name this session..."
              aria-describedby={desc.session}
              onChange={(e) => setSessionTitle(e.target.value)}
            />
          </label>
          <span id={desc.session} className="sr-only">A title for this adventure</span>
        </div>

        <label>
          Character Lore
          <textarea
            rows={5}
            placeholder="Describe their history, personality, and motivations..."
            aria-describedby={desc.lore}
            value={form.description}
            onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))}
          />
        </label>
        <span id={desc.lore} className="sr-only">Background story, personality, and motivations of your character</span>

        <label>
          Sacred Laws
          <textarea
            rows={5}
            placeholder="Rules the character must never break..."
            aria-describedby={desc.laws}
            value={listToText(form.hard_rules)}
            onChange={(e) => setForm((c) => ({ ...c, hard_rules: textToList(e.target.value) }))}
          />
        </label>
        <span id={desc.laws} className="sr-only">Hard rules your character must never break, one per line</span>

        <label>
          Voice &amp; Style
          <textarea
            rows={3}
            placeholder="How they speak and carry themselves..."
            aria-describedby={desc.voice}
            value={form.style_guide}
            onChange={(e) => setForm((c) => ({ ...c, style_guide: e.target.value }))}
          />
        </label>
        <span id={desc.voice} className="sr-only">How your character speaks and behaves</span>

        <div className="form-row">
          <label>
            Realm Name
            <input
              placeholder="Name of the world..."
              aria-describedby={desc.realm}
              value={form.world_name}
              onChange={(e) => setForm((c) => ({ ...c, world_name: e.target.value }))}
            />
          </label>
          <span id={desc.realm} className="sr-only">The name of the world your character inhabits</span>
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
            aria-describedby={desc.realmDesc}
            value={form.world_description}
            onChange={(e) => setForm((c) => ({ ...c, world_description: e.target.value }))}
          />
        </label>
        <span id={desc.realmDesc} className="sr-only">Description of the world or realm</span>

        <label>
          Established Canon
          <textarea
            rows={4}
            placeholder="Known truths of this world..."
            aria-describedby={desc.canon}
            value={form.world_canon}
            onChange={(e) => setForm((c) => ({ ...c, world_canon: e.target.value }))}
          />
        </label>
        <span id={desc.canon} className="sr-only">Known facts and history of this world</span>

        <label>
          World Laws
          <textarea
            rows={4}
            placeholder="Immutable rules of reality..."
            aria-describedby={desc.worldLaws}
            value={listToText(form.world_hard_rules)}
            onChange={(e) =>
              setForm((c) => ({ ...c, world_hard_rules: textToList(e.target.value) }))
            }
          />
        </label>
        <span id={desc.worldLaws} className="sr-only">Immutable rules of this world, one per line</span>

        <div className="tag-row">
          {selectedTemplate.tags.map((tag) => (
            <span key={tag} className="tag">
              {tag}
            </span>
          ))}
        </div>

        <div className="gm-controls">
          <label className="gm-toggle">
            <input
              type="checkbox"
              checked={gmEnabled}
              onChange={(e) => setGmEnabled(e.target.checked)}
            />
            <span className="toggle-label">✧ Game Master Mode</span>
            <span className="toggle-hint">
              {gmEnabled ? "World narration & events active" : "Character-only mode"}
            </span>
          </label>

          <label className="gm-toggle">
            <input
              type="checkbox"
              checked={worldStateEnabled}
              onChange={(e) => setWorldStateEnabled(e.target.checked)}
            />
            <span className="toggle-label">◈ World Ledger</span>
            <span className="toggle-hint">
              {worldStateEnabled ? "Canon tracked turn by turn" : "No structured canon"}
            </span>
          </label>

          <label className="gm-toggle">
            <input
              type="checkbox"
              checked={questsEnabled}
              onChange={(e) => setQuestsEnabled(e.target.checked)}
            />
            <span className="toggle-label">❖ Quests</span>
            <span className="toggle-hint">
              {questsEnabled ? "Promises & threats become quests" : "No quest journal"}
            </span>
          </label>

          {gmEnabled && (
            <div className="gm-settings">
              <div className="form-row">
                <label>
                  Current Location
                  <input
                    placeholder="Where in the world..."
                    aria-describedby={desc.location}
                    value={currentLocation}
                    onChange={(e) => setCurrentLocation(e.target.value)}
                  />
                </label>
                <span id={desc.location} className="sr-only">Where the story begins</span>
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
          <Button type="submit" disabled={isBusy}>
            ⚔ Summon Character
          </Button>
          <Button variant="secondary" type="button" disabled={isBusy} onClick={onStartSession}>
            ✦ Begin Chronicle
          </Button>
          <Button variant="secondary" type="button" onClick={onLoadOpening}>
            ↯ Load Opening
          </Button>
        </div>
      </form>
    </section>
  );
}
