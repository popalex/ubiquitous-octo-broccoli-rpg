import type { FormEvent } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { RoleplayTemplate } from "../templates";
import { listToText, textToList } from "../api";
import type { CharacterLoadPayload } from "../types";

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
  currentLocation: string;
  setCurrentLocation: (v: string) => void;
  timeOfDay: string;
  setTimeOfDay: (v: string) => void;
  onLoadCharacter: (e: FormEvent) => void;
  onStartSession: () => void;
  onLoadOpening: () => void;
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
              onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))}
            />
          </label>
          <label>
            Chronicle Title
            <input
              value={sessionTitle}
              placeholder="Name this session..."
              onChange={(e) => setSessionTitle(e.target.value)}
            />
          </label>
        </div>

        <label>
          Character Lore
          <textarea
            rows={5}
            placeholder="Describe their history, personality, and motivations..."
            value={form.description}
            onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))}
          />
        </label>

        <label>
          Sacred Laws
          <textarea
            rows={5}
            placeholder="Rules the character must never break..."
            value={listToText(form.hard_rules)}
            onChange={(e) => setForm((c) => ({ ...c, hard_rules: textToList(e.target.value) }))}
          />
        </label>

        <label>
          Voice &amp; Style
          <textarea
            rows={3}
            placeholder="How they speak and carry themselves..."
            value={form.style_guide}
            onChange={(e) => setForm((c) => ({ ...c, style_guide: e.target.value }))}
          />
        </label>

        <div className="form-row">
          <label>
            Realm Name
            <input
              placeholder="Name of the world..."
              value={form.world_name}
              onChange={(e) => setForm((c) => ({ ...c, world_name: e.target.value }))}
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
            onChange={(e) => setForm((c) => ({ ...c, world_description: e.target.value }))}
          />
        </label>

        <label>
          Established Canon
          <textarea
            rows={4}
            placeholder="Known truths of this world..."
            value={form.world_canon}
            onChange={(e) => setForm((c) => ({ ...c, world_canon: e.target.value }))}
          />
        </label>

        <label>
          World Laws
          <textarea
            rows={4}
            placeholder="Immutable rules of reality..."
            value={listToText(form.world_hard_rules)}
            onChange={(e) =>
              setForm((c) => ({ ...c, world_hard_rules: textToList(e.target.value) }))
            }
          />
        </label>

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
          <button
            className="btn btn-secondary"
            type="button"
            disabled={isBusy}
            onClick={onStartSession}
          >
            ✦ Begin Chronicle
          </button>
          <button className="btn btn-secondary" type="button" onClick={onLoadOpening}>
            ↯ Load Opening
          </button>
        </div>
      </form>
    </section>
  );
}
