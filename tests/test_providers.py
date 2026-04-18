from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
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
async def test_openai_generate_text_stream_yields_delta_chunks() -> None:
    provider = _make_openai()

    async def fake_stream(*args, **kwargs):
        for content in ["Hello", " world"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            yield chunk

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
