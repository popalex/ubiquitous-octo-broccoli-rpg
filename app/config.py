from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


ProviderName = Literal["ollama", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "small-rpg-gpt"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/roleplay"

    actor_provider: ProviderName = "ollama"
    memory_provider: ProviderName = "ollama"
    embedding_provider: ProviderName = "ollama"

    actor_model_name: str = "llama3.2:3b"
    memory_model_name: str = "llama3.2:3b"
    embedding_model_name: str = "nomic-embed-text"
    embedding_dimension: int = 768

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
    request_timeout_seconds: float = 60.0

    @property
    def actor_context_budget(self) -> int:
        return max(512, self.actor_max_input_tokens - self.actor_reserved_output_tokens)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
