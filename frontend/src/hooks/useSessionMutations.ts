import { useMutation } from "@tanstack/react-query";

import { api } from "../api";
import { withUiSpan } from "../telemetry";
import type { CharacterLoadPayload, RestResult, SessionDetail } from "../types";

type CharacterLoadResult = {
  character_card_id: string;
  world_state_id: string;
  character_name: string;
  world_name: string;
};

type SessionInitResult = {
  session_id: string;
  turn_count: number;
  gm_enabled: boolean;
  suggestions_enabled: boolean;
  current_location: string | null;
  time_of_day: string | null;
  // Resolved per-session feature flags (session override → global).
  world_state_enabled: boolean;
  quests_enabled: boolean;
  dice_enabled: boolean;
};

export type SessionInitInput = {
  character_card_id: string;
  world_state_id: string | null;
  title: string | null;
  // null inherits the backend's global default.
  gm_enabled: boolean | null;
  suggestions_enabled: boolean | null;
  current_location: string | null;
  time_of_day: string | null;
  // null inherits the backend's global setting.
  world_state_enabled: boolean | null;
  quests_enabled: boolean | null;
  dice_enabled: boolean | null;
  character_sheet_enabled: boolean | null;
  permadeath_enabled: boolean | null;
};

/** POST /character/load — upserts the character + world templates. */
export function useLoadCharacter() {
  return useMutation({
    mutationFn: (form: CharacterLoadPayload) =>
      withUiSpan(
        "ui.load_character",
        { "rpg.character_name": form.name, "rpg.world_name": form.world_name },
        () => api<CharacterLoadResult>("/character/load", { method: "POST", body: JSON.stringify(form) }),
      ),
  });
}

/** POST /session/init — starts a new chronicle. */
export function useStartSession() {
  return useMutation({
    mutationFn: (input: SessionInitInput) =>
      withUiSpan(
        "ui.new_chronicle",
        { "rpg.character_card_id": input.character_card_id, "rpg.gm_enabled": input.gm_enabled ?? "inherit" },
        () => api<SessionInitResult>("/session/init", { method: "POST", body: JSON.stringify(input) }),
      ),
  });
}

export type SessionForkInput = {
  sessionId: string;
  // Inclusive turn index to fork at; omit to fork the whole chronicle.
  atTurn?: number;
  title?: string;
};

/**
 * POST /session/{id}/fork — branches a new, independent chronicle from a turn.
 * The parent is never modified (fork-only). Returns the new session's detail.
 */
export function useForkSession() {
  return useMutation({
    mutationFn: ({ sessionId, atTurn, title }: SessionForkInput) =>
      withUiSpan(
        "ui.fork_chronicle",
        { "rpg.session_id": sessionId, "rpg.fork.at_turn": atTurn ?? "all" },
        () =>
          api<SessionDetail>(`/session/${sessionId}/fork`, {
            method: "POST",
            body: JSON.stringify({ at_turn: atTurn ?? null, title: title ?? null }),
          }),
      ),
  });
}

/**
 * POST /session/{id}/rest — recover HP (todo-rpg Phase 3). Heals a fraction of
 * max HP and advances the world; returns the updated sheet + narration beats.
 */
export function useRestSession() {
  return useMutation({
    mutationFn: (sessionId: string) =>
      withUiSpan("ui.rest", { "rpg.session_id": sessionId }, () =>
        api<RestResult>(`/session/${sessionId}/rest`, { method: "POST" }),
      ),
  });
}
