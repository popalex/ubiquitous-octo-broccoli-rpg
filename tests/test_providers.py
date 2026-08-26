from __future__ import annotations

import json
from collections.abc import Callable
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
    assert payload["suggestions"] == []

    # Post-turn judge: the canned deltas must parse into the real schemas and be
    # non-empty, so a live turn provably mutates the ledger and creates a quest.
    from app.services.quests import QuestDelta
    from app.services.world_state import LedgerDelta

    world = LedgerDelta.model_validate(payload["world_delta"])
    assert not world.is_empty()
    assert world.entities_upsert[0].name == "The Harbormaster"

    quest = QuestDelta.lenient(payload["quest_delta"])
    assert not quest.is_empty()
    assert quest.quests_new[0].slug == "the-blue-lanterns"
    assert quest.quests_new[0].quest_type == "mystery"


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


# ===========================================================================
# OpenRouterProvider (OpenAI-compatible subclass; unit, SDK mocked)
# ===========================================================================


def test_build_provider_openrouter_returns_openrouter_provider() -> None:
    from app.providers.base import build_provider
    from app.providers.openrouter_provider import OpenRouterProvider

    settings = make_test_settings(openrouter_api_key="sk-or-test")
    provider = build_provider("openrouter", "meta-llama/llama-3.1-8b-instruct", settings, slot="actor")
    assert isinstance(provider, OpenRouterProvider)
    assert provider.slot == "actor"


def test_openrouter_points_client_at_openrouter_and_uses_its_key() -> None:
    """Credentials come from the openrouter_* settings, not openai_*."""
    from app.providers.openrouter_provider import OpenRouterProvider

    settings = make_test_settings(
        openai_api_key=None,  # deliberately absent: must not be used
        openrouter_api_key="sk-or-test",
        openrouter_base_url="https://openrouter.ai/api/v1",
    )
    provider = OpenRouterProvider(model_name="meta-llama/llama-3.1-8b-instruct", settings=settings)
    assert str(provider.client.base_url).startswith("https://openrouter.ai/api/v1")
    assert provider.client.api_key == "sk-or-test"


def test_openrouter_missing_key_raises_provider_error() -> None:
    from app.providers.openrouter_provider import OpenRouterProvider

    settings = make_test_settings(openrouter_api_key=None)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider(model_name="meta-llama/llama-3.1-8b-instruct", settings=settings)


@pytest.mark.asyncio
async def test_openrouter_generate_text_inherits_openai_path() -> None:
    from app.providers.openrouter_provider import OpenRouterProvider

    settings = make_test_settings(openrouter_api_key="sk-or-test")
    provider = OpenRouterProvider(model_name="meta-llama/llama-3.1-8b-instruct", settings=settings)
    fake_resp = _fake_completion("Hello from OpenRouter")

    with patch.object(
        provider.client.chat.completions,
        "create",
        new=AsyncMock(return_value=fake_resp),
    ):
        result = await provider.generate_text(MSG, temperature=0.7, max_tokens=200)

    assert result == "Hello from OpenRouter"


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


# ===========================================================================
# OpenAIProvider over a mocked HTTP transport (SDK wire compatibility)
# ===========================================================================
#
# The OpenAIProvider tests above patch `client.chat.completions.create`, so the
# SDK never builds a request or parses a response — they pass against any SDK
# version, including one whose wire format changed underneath us. Nothing else
# covers it either: every test and the E2E stack run the mock provider, and
# OpenAIProvider is imported lazily inside build_provider, so a plain `pytest`
# run never even imports the SDK.
#
# These tests mock httpx instead of the SDK, so real request serialization,
# real SSE parsing, and the real pydantic response models all run. They are the
# guard against a silent break on an `openai` bump — see the 2.x -> 3.x upgrade.


def _with_mock_transport(
    provider: OpenAIProvider,
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAIProvider:
    """Route the provider's SDK client at `handler` instead of the network.

    Keeps the api_key and base_url the provider resolved for itself, so the
    request the handler sees proves which credentials and host it would really
    have used. That is what makes this reusable for the OpenRouter subclass.
    """
    from openai import AsyncOpenAI

    provider.client = AsyncOpenAI(
        api_key=provider.client.api_key,
        base_url=provider.client.base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider


def _openai_over_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    model: str = "gpt-4o-mini",
) -> OpenAIProvider:
    """An OpenAIProvider whose SDK client talks to `handler` instead of the network."""
    settings = make_test_settings(
        openai_api_key="sk-test",
        openai_base_url="http://openai.test/v1",
        embedding_dimension=EMBEDDING_DIM,
    )
    provider = OpenAIProvider(model_name=model, settings=settings, slot="actor")
    return _with_mock_transport(provider, handler)


def _chat_completion_body(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.mark.asyncio
async def test_openai_wire_generate_text_roundtrips_through_sdk() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_chat_completion_body("Hello from GPT"))

    provider = _openai_over_transport(handler)
    result = await provider.generate_text(MSG, temperature=0.7, max_tokens=200, json_mode=True)
    await provider.aclose()

    assert result == "Hello from GPT"
    assert seen["url"] == "http://openai.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "gpt-4o-mini"
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hello"}]
    assert seen["body"]["temperature"] == 0.7
    # Not `max_tokens`: the provider deliberately sends the newer field name.
    assert seen["body"]["max_completion_tokens"] == 200
    assert seen["body"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_openai_wire_generate_json_parses_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_completion_body('{"ok": true, "issues": []}'))

    provider = _openai_over_transport(handler)
    payload = await provider.generate_json(MSG, temperature=0.2, max_tokens=200)
    await provider.aclose()

    assert payload == {"ok": True, "issues": []}


@pytest.mark.asyncio
async def test_openai_wire_empty_completion_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_completion_body(""))

    provider = _openai_over_transport(handler)
    with pytest.raises(ProviderError, match="empty completion"):
        await provider.generate_text(MSG, temperature=0.7, max_tokens=200)
    await provider.aclose()


@pytest.mark.asyncio
async def test_openai_wire_stream_parses_sse_deltas() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        events = []
        for token in ["Hel", "lo ", "world"]:
            events.append(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-4o-mini",
                    "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                }
            )
        # Usage-only trailer, as sent for stream_options={"include_usage": True}.
        events.append(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            }
        )
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = _openai_over_transport(handler)
    collected = [c async for c in provider.generate_text_stream(MSG, temperature=0.7, max_tokens=200)]
    await provider.aclose()

    assert collected == ["Hel", "lo ", "world"]
    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_openai_wire_embed_texts_sends_dimensions_and_parses_vectors() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        count = len(seen["body"]["input"])
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": i, "embedding": [0.1] * EMBEDDING_DIM} for i in range(count)],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    provider = _openai_over_transport(handler, model="text-embedding-3-small")
    vectors = await provider.embed_texts(["hello", "world"])
    await provider.aclose()

    assert seen["url"] == "http://openai.test/v1/embeddings"
    assert seen["body"]["input"] == ["hello", "world"]
    assert seen["body"]["dimensions"] == EMBEDDING_DIM
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


# ---------------------------------------------------------------------------
# OpenRouterProvider over the same mocked transport
# ---------------------------------------------------------------------------
#
# The OpenRouter tests further up assert on client attributes and mock the SDK,
# so nothing proves a real request would carry the OpenRouter key to the
# OpenRouter host. The subclass overrides only credential resolution, and that
# is exactly the part those tests cannot see. These close that gap.


def _openrouter_over_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    model: str = "meta-llama/llama-3.1-8b-instruct",
):
    from app.providers.openrouter_provider import OpenRouterProvider

    settings = make_test_settings(
        openai_api_key=None,  # deliberately absent: leaking into the request is the bug
        openrouter_api_key="sk-or-test",
        openrouter_base_url="https://openrouter.ai/api/v1",
    )
    provider = OpenRouterProvider(model_name=model, settings=settings, slot="actor")
    return _with_mock_transport(provider, handler)


@pytest.mark.asyncio
async def test_openrouter_wire_request_carries_its_own_key_and_host() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_completion_body("Hello from OpenRouter"))

    provider = _openrouter_over_transport(handler)
    result = await provider.generate_text(MSG, temperature=0.7, max_tokens=200)
    await provider.aclose()

    assert result == "Hello from OpenRouter"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-test"
    # OpenRouter slugs contain a vendor prefix; it must survive verbatim.
    assert seen["body"]["model"] == "meta-llama/llama-3.1-8b-instruct"


@pytest.mark.asyncio
async def test_openrouter_wire_streaming_works_through_the_subclass() -> None:
    """The actor and GM slots stream, so the inherited SSE path has to hold up."""

    def handler(request: httpx.Request) -> httpx.Response:
        events = [
            {
                "id": "gen-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "meta-llama/llama-3.1-8b-instruct",
                "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
            }
            for token in ["The ", "lantern ", "flickers."]
        ]
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = _openrouter_over_transport(handler)
    collected = [c async for c in provider.generate_text_stream(MSG, temperature=0.7, max_tokens=200)]
    await provider.aclose()

    assert "".join(collected) == "The lantern flickers."
