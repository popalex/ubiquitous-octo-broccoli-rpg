export type Health = {
  status: string;
  database: string;
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
  messageType?: "chat" | "pre_narration" | "post_narration" | "event";
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
  continuity_applied: boolean;
  continuity_issues: string[];
  retrieved_memories: RetrievedMemory[];
};
