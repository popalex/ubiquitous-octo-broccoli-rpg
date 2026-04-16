from __future__ import annotations

from collections.abc import Sequence

from openai import AsyncOpenAI

from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage


class OpenAIProvider(BaseModelProvider):
    def __init__(self, model_name: str, settings) -> None:
        super().__init__(model_name=model_name, settings=settings)
        if not self.settings.openai_api_key:
            raise ProviderError("OPENAI_API_KEY is required when an OpenAI provider is selected.")

        client_kwargs = {"api_key": self.settings.openai_api_key}
        if self.settings.openai_base_url:
            client_kwargs["base_url"] = self.settings.openai_base_url
        self.client = AsyncOpenAI(**client_kwargs)

    async def generate_text(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": message.role, "content": message.content} for message in messages],
            temperature=temperature,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"} if json_mode else None,
        )
        content = response.choices[0].message.content
        if not content:
            raise ProviderError("OpenAI provider returned an empty completion.")
        return content

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self.client.embeddings.create(
            model=self.model_name,
            input=list(texts),
            dimensions=self.settings.embedding_dimension,
        )
        return [item.embedding for item in response.data]
