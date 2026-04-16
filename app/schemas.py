from datetime import datetime

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


class SessionInitResponse(ORMModel):
    session_id: str
    character_card_id: str
    world_state_id: str | None
    title: str | None
    turn_count: int


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


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    continuity_applied: bool
    continuity_issues: list[str]
    retrieved_memories: list[RetrievedMemoryItem]


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


class HealthResponse(BaseModel):
    status: str
    database: str
