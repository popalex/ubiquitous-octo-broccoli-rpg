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
    gm_narration_max_tokens: int = 150  # Keep narration short for faster responses
    request_timeout_seconds: float = 60.0

    # GM event generation settings
    event_check_interval: int = 3  # Check for events every N turns
    event_probability: float = 0.4  # Base probability of event occurrence

    @property
    def actor_context_budget(self) -> int:
        return max(512, self.actor_max_input_tokens - self.actor_reserved_output_tokens)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
