from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage


class OllamaProvider(BaseModelProvider):
    def __init__(self, model_name: str, settings) -> None:
        super().__init__(model_name=model_name, settings=settings)
        self.client = httpx.AsyncClient(
            base_url=self.settings.ollama_base_url,
            timeout=self.settings.request_timeout_seconds,
        )

    async def generate_text(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        payload = {
            "model": self.model_name,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        try:
            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Failed to call Ollama chat API at {self.settings.ollama_base_url}: {exc}") from exc

        content = response.json().get("message", {}).get("content", "")
        if not content:
            raise ProviderError("Ollama provider returned an empty completion.")
        return content

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        payload = {
            "model": self.model_name,
            "input": list(texts),
        }
        try:
            response = await self.client.post("/api/embed", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Failed to call Ollama embedding API at {self.settings.ollama_base_url}: {exc}") from exc

        embeddings = response.json().get("embeddings")
        if not embeddings:
            raise ProviderError("Ollama provider returned no embeddings.")
        return embeddings
