"""Deterministic, offline provider for full-stack E2E (TESTING.md §4 Phase 2).

Promotes the spirit of ``tests/conftest.py``'s ``MockProvider`` into a real
``build_provider("mock", …)`` slot so ``docker compose`` can run the entire
stack — frontend ↔ FastAPI ↔ Postgres — with **no Ollama**. The "LLM" is the
canned text below, so the suite exercises the real API contract and SSE plumbing
without a model, GPU, or network.

Every method is deterministic and self-contained. ``generate_json`` returns a
benign superset payload: continuity reads ``ok``/``issues``/``revised_response``
(empty revision keeps the draft); the post-turn judge reads ``world_delta``/
``quest_delta``/``suggestions`` — all consumers use ``.get()`` with defaults, so
one static dict satisfies them all without breaking a turn.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence

from app.config import Settings, get_settings
from app.providers.base import BaseModelProvider, ProviderMessage

# A fixed, deterministic in-character reply. Kept short and recognisable so
# live-mode E2E specs can assert it renders without depending on a real model.
_MOCK_REPLY = (
    "The harbor lanterns glow blue tonight, a sign the old wards still hold. "
    "Tell me what you seek, and I will guide you."
)

_MOCK_JSON: dict = {
    # Continuity check: no issues, empty revision keeps the actor draft as-is.
    "ok": True,
    "issues": [],
    "revised_response": "",
    # Post-turn judge: no canon/quest changes, no suggestion chips.
    "world_delta": {},
    "quest_delta": {},
    "suggestions": [],
}


class MockProvider(BaseModelProvider):
    """Canned, deterministic provider for offline full-stack E2E."""

    def __init__(
        self,
        model_name: str = "mock",
        settings: Settings | None = None,
        slot: str = "unknown",
    ) -> None:
        super().__init__(model_name=model_name, settings=settings or get_settings(), slot=slot)

    async def generate_text(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        return _MOCK_REPLY

    async def generate_text_stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        # Yield word-by-word so the SSE chunk path (chat.ts) is exercised the
        # way a real streaming model would drive it.
        for word in _MOCK_REPLY.split(" "):
            yield word + " "

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    async def generate_json(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        return dict(_MOCK_JSON)

    def _embed_one(self, text: str) -> list[float]:
        """A stable pseudo-embedding derived from the text hash.

        Deterministic (so retrieval ranking is reproducible) and varied per
        input (so distinct memories don't collapse to one point), without
        needing a model.
        """
        dim = self.settings.embedding_dimension
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Cycle the digest bytes into [0, 1) floats across the full dimension.
        return [digest[i % len(digest)] / 255.0 for i in range(dim)]
