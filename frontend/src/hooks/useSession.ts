import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { api } from "../api";
import type {
  CharacterSheet,
  SessionDetail,
  SessionMemory,
  SessionQuests,
  TurnRecord,
  WorldStateLedger,
} from "../types";

export const sessionKeys = {
  detail: (id: string) => ["session", id, "detail"] as const,
  turns: (id: string) => ["session", id, "turns"] as const,
  memory: (id: string) => ["session", id, "memory"] as const,
  worldState: (id: string) => ["session", id, "world-state"] as const,
  quests: (id: string) => ["session", id, "quests"] as const,
  suggestions: (id: string) => ["session", id, "suggestions"] as const,
  sheet: (id: string) => ["session", id, "sheet"] as const,
};

/** Session detail + turns — the data needed to render a resumed chronicle. */
export function useSessionDetail(sessionId: string) {
  return useQuery({
    queryKey: sessionKeys.detail(sessionId),
    queryFn: () => api<SessionDetail>(`/session/${sessionId}`),
    enabled: !!sessionId,
  });
}

export function useSessionTurns(sessionId: string) {
  return useQuery({
    queryKey: sessionKeys.turns(sessionId),
    queryFn: () => api<TurnRecord[]>(`/session/${sessionId}/turns`),
    enabled: !!sessionId,
  });
}

/**
 * Regenerated suggested-response chips for the chronicle's latest reply. Chips
 * aren't persisted, so on reload we recompute them on demand (one judge call).
 * Gated on `enabled` (the session's resolved suggestions flag) so the call is
 * skipped entirely when the feature is off; the latest exchange is stable until
 * a new turn, so the result never goes stale on its own.
 */
export function useSessionSuggestions(sessionId: string, enabled: boolean) {
  return useQuery({
    queryKey: sessionKeys.suggestions(sessionId),
    queryFn: () => api<{ suggestions: string[] }>(`/session/${sessionId}/suggestions`),
    enabled: !!sessionId && enabled,
    retry: false,
    staleTime: Infinity,
  });
}

/** Memory scrolls — may be slow on first load if the backend backfills. */
export function useSessionMemory(sessionId: string) {
  return useQuery({
    queryKey: sessionKeys.memory(sessionId),
    queryFn: () => api<SessionMemory>(`/session/${sessionId}/memory`),
    enabled: !!sessionId,
  });
}

/** World-state ledger — best-effort; ships dark behind a flag (empty v0 when off). */
export function useWorldState(sessionId: string) {
  return useQuery({
    queryKey: sessionKeys.worldState(sessionId),
    queryFn: () => api<WorldStateLedger>(`/session/${sessionId}/world-state`),
    enabled: !!sessionId,
    retry: false,
  });
}

/** Quest journal — best-effort; ships dark behind a flag (empty list when off). */
export function useSessionQuests(sessionId: string) {
  return useQuery({
    queryKey: sessionKeys.quests(sessionId),
    queryFn: () => api<SessionQuests>(`/session/${sessionId}/quests`),
    enabled: !!sessionId,
    retry: false,
  });
}

/**
 * Character sheet (todo-rpg Phase 1) — gated on `enabled` (the resolved
 * character-sheet flag). 404s when the feature is off for the chronicle, so the
 * call is skipped entirely in that case and never retried.
 */
export function useSessionSheet(sessionId: string, enabled: boolean) {
  return useQuery({
    queryKey: sessionKeys.sheet(sessionId),
    queryFn: () => api<CharacterSheet>(`/session/${sessionId}/sheet`),
    enabled: !!sessionId && enabled,
    retry: false,
  });
}

/**
 * Returns a callback that refetches the post-turn-mutated reads (memory +
 * world-state + quests) for a session. Passed to the SSE chat flow as
 * `refreshMemory`.
 */
export function useRefreshMemory(): (sessionId: string) => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(
    async (sessionId: string) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sessionKeys.memory(sessionId) }),
        queryClient.invalidateQueries({ queryKey: sessionKeys.worldState(sessionId) }),
        queryClient.invalidateQueries({ queryKey: sessionKeys.quests(sessionId) }),
        queryClient.invalidateQueries({ queryKey: sessionKeys.sheet(sessionId) }),
      ]);
    },
    [queryClient],
  );
}
