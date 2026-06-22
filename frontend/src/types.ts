export type Health = {
  status: string;
  database: string;
  mode: string;
  gm_enabled: boolean;
  suggestions_enabled: boolean;
  world_state_enabled: boolean;
  quests_enabled: boolean;
  dice_enabled: boolean;
};

export type ChronicleListItem = {
  id: string;
  title: string | null;
  status: string;
  gm_enabled: boolean;
  turn_count: number;
  created_at: string;
  updated_at: string;
  character_card_id: string;
  world_state_id: string | null;
  character_name: string | null;
  world_name: string | null;
  summary: string | null;
  suggestions_enabled: boolean;
  // Resolved per-session feature flags (session override → global).
  world_state_enabled: boolean;
  quests_enabled: boolean;
  dice_enabled: boolean;
  // Fork lineage: null parent = an original chronicle.
  parent_session_id: string | null;
  forked_at_turn: number | null;
};

export type SessionDetail = {
  id: string;
  title: string | null;
  status: string;
  gm_enabled: boolean;
  turn_count: number;
  created_at: string;
  updated_at: string;
  character_card_id: string;
  world_state_id: string | null;
  character_name: string | null;
  world_name: string | null;
  current_location: string | null;
  time_of_day: string | null;
  suggestions_enabled: boolean;
  // Resolved per-session feature flags (session override → global).
  world_state_enabled: boolean;
  quests_enabled: boolean;
  dice_enabled: boolean;
  // Fork lineage: null parent = an original chronicle.
  parent_session_id: string | null;
  forked_at_turn: number | null;
};

export type TurnRecord = {
  turn_index: number;
  role: string;
  content: string;
  turn_type: string;
};

export type CharacterLoadPayload = {
  name: string;
  description: string;
  hard_rules: string[];
  style_guide: string;
  world_name: string;
  world_description: string;
  world_canon: string;
  world_hard_rules: string[];
};

export type SessionMemory = {
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

export type WorldStateLedger = {
  session_id: string;
  version: number;
  created_at: string | null;
  state: {
    location?: { name?: string | null; description?: string | null } | null;
    entities?: Array<{
      id: string;
      name: string;
      kind?: string;
      status?: string | null;
      facts?: string[];
      relationship_to_player?: string | null;
    }>;
    inventory?: Array<{ item: string; qty?: number | null }>;
    threads?: Array<{ id: string; summary: string; status?: string }>;
    facts?: string[];
  };
};

export type QuestStage = {
  id: string;
  description: string;
  done: boolean;
};

export type Quest = {
  id: string;
  slug: string;
  title: string;
  quest_type: string;
  description: string;
  stakes: string | null;
  status: string;
  origin: string;
  stages: QuestStage[];
  resolution: string | null;
  created_turn: number;
  accepted_turn: number | null;
  last_progress_turn: number;
  resolved_turn: number | null;
  created_at: string;
  updated_at: string;
};

export type SessionQuests = {
  session_id: string;
  quests: Quest[];
};

export type QuestUpdateNotification = {
  quest_id: string;
  slug: string;
  title: string;
  status: string;
  change: string;
  detail: string | null;
};

export type RetrievedMemory = {
  id: string;
  kind: string;
  content: string;
  weighted_score: number;
  semantic_score: number;
  recency_score: number;
  importance: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "narrator";
  content: string;
  messageType?: "chat" | "pre_narration" | "post_narration" | "event" | "quest" | "roll";
  // Set on a "roll" message — renders as a dice chip instead of prose.
  roll?: DiceRoll;
  // Suggested next-action chips offered after this reply (ephemeral; only the
  // latest assistant/narrator message renders them).
  suggestions?: string[];
};

export type DiceRoll = {
  skill_label: string;
  dc: number;
  die: number; // raw d20, 1-20
  outcome: "success" | "failure" | "critical_success";
  // Why the GM set that DC — DC-encoded competence made visible.
  rationale: string | null;
};

export type GMEvent = {
  event_type: string;
  urgency: string;
  description: string;
  npcs_involved: string[];
};

export type GMChatResponse = {
  session_id: string;
  pre_narration: string | null;
  character_reply: string;
  post_narration: string | null;
  event: GMEvent | null;
  roll: DiceRoll | null;
  continuity_applied: boolean;
  continuity_issues: string[];
  retrieved_memories: RetrievedMemory[];
};
