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
from collections.abc import AsyncGenerator, Sequence

from app.config import Settings, get_settings
from app.providers.base import BaseModelProvider, ProviderMessage

# A fixed, deterministic in-character reply. Kept short and recognisable so
# live-mode E2E specs can assert it renders without depending on a real model.
_MOCK_REPLY = (
    "The harbor lanterns glow blue tonight, a sign the old wards still hold. "
    "Tell me what you seek, and I will guide you."
)

# Canned post-turn judge output. The world/quest deltas are non-empty so the
# live E2E suite can prove a turn actually mutates the ledger and creates a
# quest, and that both render — the contract Phase 1 (browser-faked /api) can't
# exercise. Shapes match LedgerDelta / QuestDelta (app/services/{world_state,
# quests}.py); applies are idempotent by entity id / quest slug, so re-running
# the judge on later turns is a harmless no-op. Continuity reads only
# ok/issues/revised_response and ignores the rest.
_MOCK_JSON: dict = {
    # Continuity check: no issues, empty revision keeps the actor draft as-is.
    "ok": True,
    "issues": [],
    "revised_response": "",
    # World-state ledger delta: one NPC + one canon fact.
    "world_delta": {
        "entities_upsert": [
            {
                "id": "harbormaster",
                "name": "The Harbormaster",
                "kind": "npc",
                "facts": ["Tends the blue harbor lanterns."],
            }
        ],
        "facts_add": ["The harbor lanterns glow blue when the old wards are active."],
    },
    # Quest delta: one new, active quest (emergent quests start active).
    "quest_delta": {
        "quests_new": [
            {
                "slug": "the-blue-lanterns",
                "title": "The Blue Lanterns",
                "quest_type": "mystery",
                "description": "Discover why the harbor lanterns burn blue.",
                "stakes": "The harbor's safety",
                "stages": [{"id": "st1", "description": "Question the harbormaster", "done": False}],
            }
        ],
        "quests_update": [],
    },
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
    ) -> AsyncGenerator[str, None]:
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
