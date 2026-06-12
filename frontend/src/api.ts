import { templates } from "./templates";
import type { CharacterLoadPayload } from "./types";

export const storageKeys = {
  characterCardId: "small-rpg:character-card-id",
  gmEnabled: "small-rpg:gm-enabled",
  worldStateEnabled: "small-rpg:world-state-enabled",
  questsEnabled: "small-rpg:quests-enabled",
  worldStateId: "small-rpg:world-state-id",
  sessionId: "small-rpg:session-id",
  sessionTitle: "small-rpg:session-title",
  selectedTemplate: "small-rpg:selected-template",
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail: string;
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      detail = (await response.text()) || response.statusText;
    }
    throw new Error(detail || "Request failed");
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function listToText(items: string[]): string {
  return items.join("\n");
}

export function textToList(text: string): string[] {
  return text
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function createInitialForm(): CharacterLoadPayload {
  return { ...templates[0].characterLoad };
}
