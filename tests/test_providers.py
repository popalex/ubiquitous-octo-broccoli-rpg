from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import ProviderError, ProviderMessage
from app.providers.ollama_provider import OllamaProvider
from app.providers.openai_provider import OpenAIProvider
from tests.conftest import MockProvider, make_test_settings

EMBEDDING_DIM = 768
MSG = [ProviderMessage(role="user", content="Hello")]


# ===========================================================================
# MockProvider (sanity)
# ===========================================================================


@pytest.mark.asyncio
async def test_mock_provider_generate_text_returns_configured_response() -> None:
    provider = MockProvider()
    provider.set_text_response("Custom reply")
    result = await provider.generate_text(MSG, temperature=0.7, max_tokens=100)
    assert result == "Custom reply"


@pytest.mark.asyncio
async def test_mock_provider_generate_json_returns_configured_dict() -> None:
    provider = MockProvider()
    payload = {"key": "value", "count": 42}
    provider.set_json_response(payload)
    result = await provider.generate_json(MSG, temperature=0.2, max_tokens=200)
    assert result == payload


@pytest.mark.asyncio
async def test_mock_provider_embed_texts_returns_correct_dimension() -> None:
    provider = MockProvider()
    results = await provider.embed_texts(["hello", "world"])
    assert len(results) == 2
    for vec in results:
        assert len(vec) == EMBEDDING_DIM


# ===========================================================================
# Built-in mock provider (full-stack E2E Phase 2 — build_provider("mock"))
# ===========================================================================


def test_build_provider_mock_returns_mock_provider() -> None:
    from app.providers.base import build_provider
    from app.providers.mock_provider import MockProvider as BuiltinMockProvider

    settings = make_test_settings()
    provider = build_provider("mock", "mock", settings, slot="actor")
    assert isinstance(provider, BuiltinMockProvider)
    assert provider.slot == "actor"


@pytest.mark.asyncio
async def test_builtin_mock_generate_text_returns_canned_reply() -> None:
    from app.providers.mock_provider import MockProvider as BuiltinMockProvider

    provider = BuiltinMockProvider(settings=make_test_settings())
    result = await provider.generate_text(MSG, temperature=0.7, max_tokens=100)
    # The live-mode E2E specs assert this substring renders.
    assert "glow blue tonight" in result


@pytest.mark.asyncio
async def test_builtin_mock_stream_chunks_join_to_full_reply() -> None:
    from app.providers.mock_provider import MockProvider as BuiltinMockProvider

    provider = BuiltinMockProvider(settings=make_test_settings())
    chunks = [c async for c in provider.generate_text_stream(MSG, temperature=0.7, max_tokens=100)]
    assert len(chunks) > 1  # streamed word-by-word, not a single blob
    full = await provider.generate_text(MSG, temperature=0.7, max_tokens=100)
    assert "".join(chunks).strip() == full


@pytest.mark.asyncio
async def test_builtin_mock_generate_json_satisfies_all_consumers() -> None:
    from app.providers.mock_provider import MockProvider as BuiltinMockProvider

    provider = BuiltinMockProvider(settings=make_test_settings())
    payload = await provider.generate_json(MSG, temperature=0.2, max_tokens=200)
    # Continuity reads these; empty revision keeps the draft.
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert payload["revised_response"] == ""
    # Post-turn judge reads these.
    assert payload["world_delta"] == {}
    assert payload["quest_delta"] == {}
    assert payload["suggestions"] == []


@pytest.mark.asyncio
async def test_builtin_mock_embeddings_deterministic_and_varied() -> None:
    from app.providers.mock_provider import MockProvider as BuiltinMockProvider

    provider = BuiltinMockProvider(settings=make_test_settings())
    first = await provider.embed_texts(["hello", "world"])
    second = await provider.embed_texts(["hello", "world"])
    assert all(len(v) == EMBEDDING_DIM for v in first)
    assert first == second  # deterministic
    assert first[0] != first[1]  # distinct inputs don't collapse


# ===========================================================================
# OllamaProvider (unit, httpx mocked)
# ===========================================================================


def _make_ollama() -> OllamaProvider:
    settings = make_test_settings(ollama_base_url="http://localhost:11434")
    return OllamaProvider(model_name="llama3", settings=settings)


def _make_streaming_response(chunks: list[dict]) -> MagicMock:
    """Build a fake httpx streaming context manager."""

    async def aiter_lines():
        for chunk in chunks:
            yield json.dumps(chunk)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = aiter_lines
    mock_response.status_code = 200

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


@pytest.mark.asyncio
async def test_ollama_generate_text_sends_payload_and_parses_response() -> None:
    provider = _make_ollama()
    chunks = [
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " there"}, "done": True},
    ]
    ctx = _make_streaming_response(chunks)

    with patch.object(provider.client, "stream", return_value=ctx) as mock_stream:
        result = await provider.generate_text(MSG, temperature=0.5, max_tokens=100)

    assert result == "Hello there"
    mock_stream.assert_called_once()
    call_kwargs = mock_stream.call_args
    assert call_kwargs[0][0] == "POST"
    assert call_kwargs[0][1] == "/api/chat"


@pytest.mark.asyncio
async def test_ollama_generate_text_stream_yields_chunks() -> None:
    provider = _make_ollama()
    chunks = [
        {"message": {"content": "Chunk1"}, "done": False},
        {"message": {"content": "Chunk2"}, "done": True},
    ]
    ctx = _make_streaming_response(chunks)

    with patch.object(provider.client, "stream", return_value=ctx):
        collected = []
        async for chunk in provider.generate_text_stream(MSG, temperature=0.5, max_tokens=100):
            collected.append(chunk)

    assert collected == ["Chunk1", "Chunk2"]


@pytest.mark.asyncio
async def test_ollama_embed_texts_returns_embeddings() -> None:
    provider = _make_ollama()
    fake_embeddings = [[0.1] * EMBEDDING_DIM, [0.2] * EMBEDDING_DIM]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"embeddings": fake_embeddings})

    with patch.object(provider.client, "post", new=AsyncMock(return_value=mock_response)):
        result = await provider.embed_texts(["hello", "world"])

    assert result == fake_embeddings


@pytest.mark.asyncio
async def test_ollama_connection_error_raises_provider_error() -> None:
    provider = _make_ollama()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(provider.client, "stream", return_value=mock_ctx):
        with pytest.raises(ProviderError):
            await provider.generate_text(MSG, temperature=0.5, max_tokens=100)


@pytest.mark.asyncio
async def test_ollama_generate_text_raises_on_mid_stream_error() -> None:
    """An Ollama error line mid-stream must not be silently swallowed."""
    provider = _make_ollama()
    chunks = [
        {"message": {"content": "The scent of incense wa"}, "done": False},
        {"error": "model runner has unexpectedly stopped"},
    ]
    ctx = _make_streaming_response(chunks)

    with patch.object(provider.client, "stream", return_value=ctx):
        with pytest.raises(ProviderError, match="mid-stream"):
            await provider.generate_text(MSG, temperature=0.5, max_tokens=100)


@pytest.mark.asyncio
async def test_ollama_generate_text_stream_raises_on_mid_stream_error() -> None:
    """A streamed Ollama error line surfaces as ProviderError after partial chunks."""
    provider = _make_ollama()
    chunks = [
        {"message": {"content": "The scent of incense wa"}, "done": False},
        {"error": "model runner has unexpectedly stopped"},
    ]
    ctx = _make_streaming_response(chunks)

    collected: list[str] = []
    with patch.object(provider.client, "stream", return_value=ctx):
        with pytest.raises(ProviderError, match="mid-stream"):
            async for chunk in provider.generate_text_stream(MSG, temperature=0.5, max_tokens=100):
                collected.append(chunk)

    assert collected == ["The scent of incense wa"]


@pytest.mark.asyncio
async def test_ollama_omits_num_predict_when_max_tokens_non_positive() -> None:
    """max_tokens <= 0 means no output limit: num_predict must be omitted."""
    provider = _make_ollama()
    chunks = [{"message": {"content": "ok"}, "done": True}]
    ctx = _make_streaming_response(chunks)

    with patch.object(provider.client, "stream", return_value=ctx) as mock_stream:
        await provider.generate_text(MSG, temperature=0.5, max_tokens=0)

    options = mock_stream.call_args.kwargs["json"]["options"]
    assert "num_predict" not in options


# ===========================================================================
# OpenAIProvider (unit, SDK mocked)
# ===========================================================================


def _make_openai() -> OpenAIProvider:
    settings = make_test_settings(openai_api_key="sk-test")
    return OpenAIProvider(model_name="gpt-4o-mini", settings=settings)


def _fake_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    resp.usage = usage
    return resp


@pytest.mark.asyncio
async def test_openai_generate_text_calls_completions_and_returns_content() -> None:
    provider = _make_openai()
    fake_resp = _fake_completion("Hello from GPT")

    with patch.object(
        provider.client.chat.completions,
        "create",
        new=AsyncMock(return_value=fake_resp),
    ):
        result = await provider.generate_text(MSG, temperature=0.7, max_tokens=200)

    assert result == "Hello from GPT"


@pytest.mark.asyncio
async def test_openai_omits_max_tokens_when_non_positive() -> None:
    """max_tokens <= 0 means no output limit: max_completion_tokens must be omitted."""
    provider = _make_openai()
    fake_resp = _fake_completion("ok")

    mock_create = AsyncMock(return_value=fake_resp)
    with patch.object(provider.client.chat.completions, "create", new=mock_create):
        await provider.generate_text(MSG, temperature=0.7, max_tokens=0)

    assert "max_completion_tokens" not in mock_create.call_args.kwargs


@pytest.mark.asyncio
async def test_openai_generate_text_stream_yields_delta_chunks() -> None:
    provider = _make_openai()

    async def fake_stream(*args, **kwargs):
        for content in ["Hello", " world"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            chunk.usage = None
            yield chunk

        # Final usage chunk mirrors OpenAI stream_options={"include_usage": True}
        usage_chunk = MagicMock()
        usage_chunk.choices = []
        usage = MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 5
        usage_chunk.usage = usage
        yield usage_chunk

    with patch.object(
        provider.client.chat.completions,
        "create",
        new=AsyncMock(return_value=fake_stream()),
    ):
        collected = []
        async for chunk in provider.generate_text_stream(MSG, temperature=0.7, max_tokens=200):
            collected.append(chunk)

    assert collected == ["Hello", " world"]


@pytest.mark.asyncio
async def test_openai_embed_texts_calls_embeddings_endpoint() -> None:
    provider = _make_openai()
    fake_embedding = [0.1] * EMBEDDING_DIM

    item = MagicMock()
    item.embedding = fake_embedding
    fake_resp = MagicMock()
    fake_resp.data = [item]
    usage = MagicMock()
    usage.prompt_tokens = 3
    fake_resp.usage = usage

    with patch.object(
        provider.client.embeddings,
        "create",
        new=AsyncMock(return_value=fake_resp),
    ):
        result = await provider.embed_texts(["hello"])

    assert result == [fake_embedding]


@pytest.mark.asyncio
async def test_openai_api_error_raises_provider_error() -> None:
    from openai import APIError

    provider = _make_openai()

    with patch.object(
        provider.client.chat.completions,
        "create",
        new=AsyncMock(side_effect=APIError("quota exceeded", request=MagicMock(), body=None)),
    ):
        with pytest.raises(Exception):
            await provider.generate_text(MSG, temperature=0.7, max_tokens=200)


# ---------------------------------------------------------------------------
# Provider slot labels (token metrics per orchestrator slot — TODO 5b)
# ---------------------------------------------------------------------------


def test_build_provider_threads_slot_label() -> None:
    from app.providers.base import build_provider

    settings = make_test_settings()
    provider = build_provider("ollama", "llama3.2:3b", settings, slot="actor")
    assert provider.slot == "actor"
    # Default stays harmless for callers that don't care.
    assert build_provider("ollama", "llama3.2:3b", settings).slot == "unknown"


def test_orchestrator_labels_all_four_slots() -> None:
    from app.services.orchestrator import OrchestratorService

    settings = make_test_settings()
    slots: list[str] = []

    def record(provider_name, model_name, settings_, slot="unknown"):
        slots.append(slot)
        return MockProvider()

    with patch("app.services.orchestrator.build_provider", side_effect=record):
        OrchestratorService(settings)

    assert slots == ["actor", "memory", "embedding", "gm"]
