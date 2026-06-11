import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { api } from "../api";
import type { SessionDetail, SessionMemory, SessionQuests, TurnRecord, WorldStateLedger } from "../types";

export const sessionKeys = {
  detail: (id: string) => ["session", id, "detail"] as const,
  turns: (id: string) => ["session", id, "turns"] as const,
  memory: (id: string) => ["session", id, "memory"] as const,
  worldState: (id: string) => ["session", id, "world-state"] as const,
  quests: (id: string) => ["session", id, "quests"] as const,
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
      ]);
    },
    [queryClient],
  );
}
