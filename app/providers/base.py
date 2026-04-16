from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from app.config import Settings, get_settings


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class ProviderMessage:
    role: str
    content: str


class BaseModelProvider(ABC):
    def __init__(self, model_name: str, settings: Settings | None = None) -> None:
        self.model_name = model_name
        self.settings = settings or get_settings()

    @abstractmethod
    async def generate_text(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    async def generate_json(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        raw_text = await self.generate_text(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.__class__.__name__} returned invalid JSON: {raw_text}") from exc


def build_provider(provider_name: str, model_name: str, settings: Settings | None = None) -> BaseModelProvider:
    resolved_settings = settings or get_settings()
    if provider_name == "openai":
        from app.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(model_name=model_name, settings=resolved_settings)

    if provider_name == "ollama":
        from app.providers.ollama_provider import OllamaProvider

        return OllamaProvider(model_name=model_name, settings=resolved_settings)

    raise ProviderError(f"Unsupported provider: {provider_name}")
