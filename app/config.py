from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "small-rpg-gpt"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/roleplay"

    # Dev mode: use a single model for all LLM tasks to save RAM
    dev_mode: bool = False
    dev_model_name: str = "llama3.2:3b"

    actor_provider: ProviderName = "ollama"
    memory_provider: ProviderName = "ollama"
    embedding_provider: ProviderName = "ollama"
    gm_provider: ProviderName = "ollama"

    actor_model_name: str = "llama3.2:8b"
    memory_model_name: str = "phi3:mini"
    embedding_model_name: str = "nomic-embed-text"
    gm_model_name: str = "llama3.2:8b"
    embedding_dimension: int = 768

    @model_validator(mode="after")
    def apply_dev_mode(self) -> Self:
        """In dev mode, override all LLM models to use a single model (saves RAM)."""
        if self.dev_mode:
            self.actor_model_name = self.dev_model_name
            self.memory_model_name = self.dev_model_name
            self.gm_model_name = self.dev_model_name
            # Increase timeout for model swapping on low-RAM systems
            if self.request_timeout_seconds < 180.0:
                self.request_timeout_seconds = 180.0
        return self

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"

    retrieval_top_k: int = 8
    retrieval_candidate_pool: int = 20
    recency_half_life_hours: int = 72
    memory_summary_interval: int = 6

    actor_max_input_tokens: int = 6000
    actor_reserved_output_tokens: int = 500
    actor_temperature: float = 0.7
    continuity_temperature: float = 0.2
    gm_temperature: float = 0.8
    gm_max_output_tokens: int = 800
    gm_narration_max_tokens: int = 0  # hard provider cap; 0 = no limit (avoids mid-word truncation)
    # Graceful length control: once narration passes this many tokens, stop at the
    # NEXT sentence boundary instead of cutting mid-word. 0 disables (truly unbounded).
    gm_narration_soft_limit_tokens: int = 1000
    request_timeout_seconds: float = 60.0

    # Default GM mode for new sessions: /session/init inherits it when the
    # request omits gm_enabled, and the UI seeds its toggle from /health.
    gm_enabled: bool = False

    # GM event generation settings
    event_check_interval: int = 3  # Check for events every N turns
    event_probability: float = 0.4  # Base probability of event occurrence

    # World-state ledger: an authoritative, structured record of canon
    # (entities, inventory, threads, location, facts) injected as hard
    # constraints and updated every turn. Ships dark behind this flag.
    world_state_enabled: bool = False
    world_state_max_entities: int = 30
    world_state_max_threads: int = 20
    world_state_max_facts: int = 40
    world_state_extract_max_tokens: int = 800

    # Quest system: AI-tracked narrative arcs (GM offers, emergent player
    # promises, escalation of neglected arcs). Ships dark behind this flag,
    # like world_state. Turn-based knobs are in raw turn_count units — GM mode
    # advances turn_count by 2-3 per exchange, so 12 turns is ~4-6 exchanges.
    quests_enabled: bool = False
    quest_max_active: int = 5  # cap of non-terminal quests tracked/injected
    quest_max_stages: int = 8  # per-quest stage cap
    quest_extraction_interval: int = 1  # run the post-turn judge every N turns
    quest_escalation_turns: int = 12  # turns without progress before escalation
    quest_extract_max_tokens: int = 700
    quest_temperature: float = 0.2

    # Unified post-turn judge (§2): when on, the per-turn world-state and quest
    # extractions are folded into ONE LLM call (PostTurnJudgeService) instead of
    # two. Memory (facts + episode summary) stays on its own cadence. Default-on
    # after baking in dev; the legacy two-call path remains the fallback when off
    # (pending removal in a follow-up).
    post_turn_judge_enabled: bool = True
    post_turn_judge_max_tokens: int = 1100

    @property
    def actor_context_budget(self) -> int:
        return max(512, self.actor_max_input_tokens - self.actor_reserved_output_tokens)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
