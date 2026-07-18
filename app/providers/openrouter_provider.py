from __future__ import annotations

from app.providers.openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter (https://openrouter.ai) served over the OpenAI wire protocol.

    Everything — chat, streaming, JSON, embeddings — is inherited from
    OpenAIProvider; only the credentials differ, so the openrouter provider can
    run alongside a real `openai` slot without sharing a key or base URL.
    Model names are OpenRouter slugs, e.g. ``meta-llama/llama-3.1-8b-instruct``.
    """

    def _resolve_credentials(self) -> tuple[str | None, str | None]:
        return self.settings.openrouter_api_key, self.settings.openrouter_base_url

    def _missing_key_message(self) -> str:
        return "OPENROUTER_API_KEY is required when the openrouter provider is selected."
