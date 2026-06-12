from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CharacterLoadRequest(BaseModel):
    name: str
    description: str
    hard_rules: list[str] = Field(default_factory=list)
    style_guide: str | None = None
    world_name: str
    world_description: str
    world_canon: str = ""
    world_hard_rules: list[str] = Field(default_factory=list)


class CharacterLoadResponse(ORMModel):
    character_card_id: str
    world_state_id: str
    character_name: str
    world_name: str


class SessionInitRequest(BaseModel):
    character_card_id: str
    world_state_id: str | None = None
    title: str | None = None
    # None inherits the global default (settings.gm_enabled). Unlike the two
    # feature flags below, the session stores the resolved value (no NULL).
    gm_enabled: bool | None = None
    current_location: str | None = None
    time_of_day: str | None = None
    # Per-session feature overrides; None inherits the global setting.
    world_state_enabled: bool | None = None
    quests_enabled: bool | None = None


class SessionInitResponse(ORMModel):
    session_id: str
    character_card_id: str
    world_state_id: str | None
    title: str | None
    turn_count: int
    gm_enabled: bool
    current_location: str | None
    time_of_day: str | None
    # Resolved (override → global), not the raw nullable override.
    world_state_enabled: bool
    quests_enabled: bool


class ChatRequest(BaseModel):
    session_id: str
    user_message: str


class RetrievedMemoryItem(BaseModel):
    id: str
    kind: str
    content: str
    weighted_score: float
    semantic_score: float
    recency_score: float
    importance: float


class QuestUpdateNotification(BaseModel):
    """A quest change surfaced to the client (response field or SSE event)."""

    quest_id: str
    slug: str
    title: str
    status: str
    change: str  # offered | started | advanced | escalated | completed | failed | abandoned
    detail: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    continuity_applied: bool
    continuity_issues: list[str]
    retrieved_memories: list[RetrievedMemoryItem]
    quest_updates: list[QuestUpdateNotification] = Field(default_factory=list)


class MemoryFactResponse(ORMModel):
    id: str
    content: str
    importance: float
    created_at: datetime


class EpisodeSummaryResponse(ORMModel):
    id: str
    content: str
    importance: float
    start_turn_index: int
    end_turn_index: int
    created_at: datetime


class RelationshipStateResponse(ORMModel):
    id: str
    source_entity: str
    target_entity: str
    status: str
    notes: str | None
    importance: float
    updated_at: datetime


class SessionMemoryResponse(BaseModel):
    session_id: str
    facts: list[MemoryFactResponse]
    episode_summaries: list[EpisodeSummaryResponse]
    relationships: list[RelationshipStateResponse]


class TurnResponse(ORMModel):
    turn_index: int
    role: str
    content: str
    turn_type: str


class SessionListItem(BaseModel):
    id: str
    title: str | None
    status: str
    gm_enabled: bool
    turn_count: int
    created_at: datetime
    updated_at: datetime
    character_card_id: str
    world_state_id: str | None
    character_name: str | None
    world_name: str | None
    summary: str | None
    # Resolved (override → global), not the raw nullable override.
    world_state_enabled: bool
    quests_enabled: bool


class SessionListResponse(BaseModel):
    sessions: list[SessionListItem]


class SessionDetailResponse(BaseModel):
    id: str
    title: str | None
    status: str
    gm_enabled: bool
    turn_count: int
    created_at: datetime
    updated_at: datetime
    character_card_id: str
    world_state_id: str | None
    character_name: str | None
    world_name: str | None
    current_location: str | None
    time_of_day: str | None
    # Resolved (override → global), not the raw nullable override.
    world_state_enabled: bool
    quests_enabled: bool


class QuestStageSchema(BaseModel):
    id: str
    description: str
    done: bool = False


class QuestResponse(ORMModel):
    id: str
    slug: str
    title: str
    quest_type: str
    description: str
    stakes: str | None
    status: str
    origin: str
    stages: list[QuestStageSchema]
    resolution: str | None
    created_turn: int
    accepted_turn: int | None
    last_progress_turn: int
    resolved_turn: int | None
    created_at: datetime
    updated_at: datetime


class SessionQuestsResponse(BaseModel):
    session_id: str
    quests: list[QuestResponse]


class QuestPatchRequest(BaseModel):
    status: Literal["abandoned"]


class WorldStateResponse(BaseModel):
    """Current (or a historical) world-state ledger snapshot for a session."""

    session_id: str
    version: int
    state: dict
    created_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str
    database: str
    mode: str
    gm_enabled: bool
    world_state_enabled: bool
    quests_enabled: bool


# =============================================================================
# GAME MASTER SCHEMAS
# =============================================================================


class GMNarrationRequest(BaseModel):
    """Request for GM narration generation."""

    session_id: str
    player_action: str
    scene_context: str | None = None


class GMNarrationResponse(BaseModel):
    """Response containing GM narration."""

    session_id: str
    narration: str
    event_triggered: bool = False
    event_description: str | None = None


class GMEventCheckRequest(BaseModel):
    """Request to check if an event should trigger."""

    session_id: str
    location: str = "unknown"
    time_of_day: str = "unknown"


class GMEventCheckResponse(BaseModel):
    """Response from event check."""

    should_trigger: bool
    event_type: str
    event_seed: str
    urgency: str
    reasoning: str


class GMEventGenerateRequest(BaseModel):
    """Request to generate a full event."""

    session_id: str
    event_seed: str
    event_type: str
    urgency: str = "gradual"


class GMEventGenerateResponse(BaseModel):
    """Response containing generated event."""

    event_type: str
    urgency: str
    description: str
    npcs_involved: list[str] = Field(default_factory=list)


class GMSceneTransitionRequest(BaseModel):
    """Request for scene transition narration."""

    session_id: str
    previous_scene: str
    transition_type: str
    destination: str


class GMSceneTransitionResponse(BaseModel):
    """Response containing transition narration."""

    narration: str
    time_passed: str
    new_scene_elements: list[str] = Field(default_factory=list)


class NPCDialogueRequest(BaseModel):
    """Request for NPC dialogue generation."""

    session_id: str
    npc_name: str
    npc_description: str
    npc_disposition: str = "neutral"
    npc_goal: str = ""
    player_statement: str


class NPCDialogueResponse(BaseModel):
    """Response containing NPC dialogue."""

    npc_name: str
    dialogue: str


class GMChatRequest(BaseModel):
    """
    Enhanced chat request that supports GM-driven gameplay.

    When gm_mode is True, the GM generates narration and potentially
    events before/after the character response.
    """

    session_id: str
    user_message: str
    gm_mode: bool = False
    location: str | None = None
    time_of_day: str | None = None


class GMChatResponse(BaseModel):
    """
    Enhanced chat response with GM elements.

    Includes pre-narration (scene setting), character reply,
    post-narration (consequences), and any triggered events.
    """

    session_id: str
    pre_narration: str | None = None
    character_reply: str
    post_narration: str | None = None
    event: GMEventGenerateResponse | None = None
    continuity_applied: bool
    continuity_issues: list[str]
    retrieved_memories: list[RetrievedMemoryItem]
    quest_updates: list[QuestUpdateNotification] = Field(default_factory=list)
