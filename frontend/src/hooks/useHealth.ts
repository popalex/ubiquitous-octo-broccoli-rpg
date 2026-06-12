import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import type { Health } from "../types";

const ERROR_HEALTH: Health = {
  status: "error",
  database: "error",
  mode: "unknown",
  gm_enabled: false,
  world_state_enabled: false,
  quests_enabled: false,
};

/**
 * Polls /health every 15s. Returns a never-null Health: the query data while
 * healthy, an explicit error sentinel on failure, or `null` before first load.
 */
export function useHealth(): Health | null {
  const { data, isError } = useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/health"),
    refetchInterval: 15_000,
    retry: false,
  });

  if (data) return data;
  if (isError) return ERROR_HEALTH;
  return null;
}
