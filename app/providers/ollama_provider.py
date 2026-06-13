from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence

import httpx

from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
from app.telemetry import (
    llm_latency,
    llm_span,
    record_llm_tokens,
    record_span_error,
    set_completion,
    set_prompt,
    tracer,
)

logger = logging.getLogger(__name__)


def _ollama_options(temperature: float, max_tokens: int) -> dict:
    """Build Ollama request options. ``max_tokens <= 0`` means no output limit
    (num_predict omitted, so Ollama generates until a natural stop)."""
    options: dict = {"temperature": temperature}
    if max_tokens and max_tokens > 0:
        options["num_predict"] = max_tokens
    return options


class OllamaProvider(BaseModelProvider):
    def __init__(self, model_name: str, settings, slot: str = "unknown") -> None:
        super().__init__(model_name=model_name, settings=settings, slot=slot)
        # Use longer read timeout for streaming responses
        self.client = httpx.AsyncClient(
            base_url=self.settings.ollama_base_url,
            timeout=httpx.Timeout(
                connect=30.0,
                read=self.settings.request_timeout_seconds,
                write=30.0,
                pool=30.0,
            ),
        )

    async def generate_text(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        """Generate text using streaming internally to avoid Ollama timeout."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "stream": True,  # Use streaming to avoid Ollama's internal timeout
            "options": _ollama_options(temperature, max_tokens),
        }
        if json_mode:
            payload["format"] = "json"

        content_parts: list[str] = []
        with llm_span(
            "llm.generate_text",
            "ollama",
            self.model_name,
            slot=self.slot,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ) as span:
            input_tokens = output_tokens = None
            try:
                logger.info("Starting streaming request to Ollama model=%s", self.model_name)
                async with self.client.stream("POST", "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    logger.info("Ollama stream opened, status=%s", response.status_code)
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                            if chunk.get("error"):
                                raise ProviderError(f"Ollama returned an error mid-stream: {chunk['error']}")
                            part = chunk.get("message", {}).get("content", "")
                            logger.debug("Received chunk from Ollama: %s", part[:100])
                            if part:
                                content_parts.append(part)
                            if chunk.get("done"):
                                input_tokens = chunk.get("prompt_eval_count")
                                output_tokens = chunk.get("eval_count")
                        except json.JSONDecodeError:
                            logger.warning("Skipped non-JSON line: %s", line[:100])
                            continue
                logger.info(
                    "Ollama stream completed, total parts=%d, total_len=%d",
                    len(content_parts),
                    len("".join(content_parts)),
                )
            except httpx.HTTPError as exc:
                logger.exception("Ollama chat API error for model=%s", self.model_name)
                raise ProviderError(
                    f"Failed to call Ollama chat API at {self.settings.ollama_base_url}: {exc}"
                ) from exc

            content = "".join(content_parts)
            if not content:
                raise ProviderError("Ollama provider returned an empty completion.")
            set_completion(span, content)
            if input_tokens or output_tokens:
                span.set_attribute("gen_ai.usage.input_tokens", input_tokens or 0)
                span.set_attribute("gen_ai.usage.output_tokens", output_tokens or 0)
                record_llm_tokens("ollama", self.model_name, input_tokens, output_tokens, slot=self.slot)
            return content

    async def generate_text_stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """Stream text chunks as they are generated by Ollama."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "stream": True,
            "options": _ollama_options(temperature, max_tokens),
        }

        # Manual span (not current) because this generator yields between awaits.
        span = tracer.start_span("llm.generate_text_stream")
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", self.model_name)
        span.set_attribute("rpg.slot", self.slot)
        span.set_attribute("gen_ai.request.temperature", temperature)
        span.set_attribute("gen_ai.request.max_tokens", max_tokens)
        set_prompt(span, messages)
        parts: list[str] = []
        input_tokens = output_tokens = None
        start = time.perf_counter()
        try:
            async with self.client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise ProviderError(f"Ollama returned an error mid-stream: {chunk['error']}")
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        parts.append(content)
                        yield content
                    if chunk.get("done"):
                        input_tokens = chunk.get("prompt_eval_count")
                        output_tokens = chunk.get("eval_count")
            set_completion(span, "".join(parts))
            if input_tokens or output_tokens:
                span.set_attribute("gen_ai.usage.input_tokens", input_tokens or 0)
                span.set_attribute("gen_ai.usage.output_tokens", output_tokens or 0)
                record_llm_tokens("ollama", self.model_name, input_tokens, output_tokens, slot=self.slot)
        except httpx.HTTPError as exc:
            logger.exception("Ollama stream API error for model=%s", self.model_name)
            record_span_error(span, exc)
            raise ProviderError(
                f"Failed to stream from Ollama chat API at {self.settings.ollama_base_url}: {exc}"
            ) from exc
        except Exception as exc:
            record_span_error(span, exc)
            raise
        finally:
            llm_latency.record(
                (time.perf_counter() - start) * 1000.0,
                {"gen_ai.system": "ollama", "gen_ai.request.model": self.model_name},
            )
            span.end()

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        payload = {
            "model": self.model_name,
            "input": list(texts),
        }
        with llm_span("llm.embed_texts", "ollama", self.model_name, slot=self.slot) as span:
            span.set_attribute("gen_ai.embed.input_count", len(texts))
            try:
                response = await self.client.post("/api/embed", json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.exception("Ollama embedding API error for model=%s", self.model_name)
                raise ProviderError(
                    f"Failed to call Ollama embedding API at {self.settings.ollama_base_url}: {exc}"
                ) from exc

            embeddings = response.json().get("embeddings")
            if not embeddings:
                raise ProviderError("Ollama provider returned no embeddings.")
            return embeddings
