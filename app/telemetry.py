"""OpenTelemetry bootstrap for the backend.

Wires traces, metrics, and logs to an OTLP collector (Grafana LGTM in this
project) and exposes a shared ``tracer`` plus a few metric instruments and
helpers used by the providers and orchestrator.

Telemetry only activates when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set (it is in
docker-compose). When unset — e.g. during ``pytest`` — ``setup_telemetry`` is a
no-op and the module-level instruments resolve to the OTel no-op API, so
instrumented code keeps working without a collector.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# When True ("full" mode), spans carry the actual LLM prompt + completion text
# and user messages. When False ("metadata" mode), only model/token/latency
# metadata is captured — everything else still works, just without content.
CAPTURE_CONTENT = _env_bool("OTEL_CAPTURE_CONTENT", True)

# Shared tracer + metric instruments. These bind to the no-op providers until
# ``setup_telemetry`` installs the real ones (OTel uses proxy objects), so they
# are safe to import and use at module load time.
tracer = trace.get_tracer("rpg-backend")
_meter = metrics.get_meter("rpg-backend")

# Units intentionally omitted so the Prometheus series names stay predictable
# (no unit suffix): rpg_llm_tokens_total, rpg_llm_latency_bucket, etc. Display
# units are set on the Grafana panels instead. Latency is recorded in ms.
llm_tokens = _meter.create_counter(
    "rpg.llm.tokens", description="LLM tokens consumed, by direction"
)
llm_latency = _meter.create_histogram(
    "rpg.llm.latency", description="LLM call wall-clock latency (ms)"
)
chat_turns = _meter.create_counter(
    "rpg.chat.turns", description="Completed chat turns"
)
retrieval_selected = _meter.create_histogram(
    "rpg.retrieval.selected", description="Memories selected per retrieval"
)


def messages_to_json(messages: Sequence) -> str:
    """Serialize provider messages for the ``gen_ai.prompt`` span attribute."""
    return json.dumps([{"role": m.role, "content": m.content} for m in messages])


def set_prompt(span, messages: Sequence) -> None:
    """Attach the prompt to a span — only in full-content mode."""
    if CAPTURE_CONTENT:
        span.set_attribute("gen_ai.prompt", messages_to_json(messages))


def set_completion(span, text: str | None) -> None:
    """Attach the completion to a span — only in full-content mode."""
    if CAPTURE_CONTENT and text:
        span.set_attribute("gen_ai.completion", text)


def record_span_error(span, exc: BaseException) -> None:
    """Mark a span failed and attach the exception, so failed turns are
    filterable in Tempo with `{ status = error }`."""
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


def record_llm_tokens(system: str, model: str, input_tokens: int | None, output_tokens: int | None) -> None:
    attrs = {"gen_ai.system": system, "gen_ai.request.model": model}
    if input_tokens is not None:
        llm_tokens.add(input_tokens, {**attrs, "gen_ai.token.direction": "input"})
    if output_tokens is not None:
        llm_tokens.add(output_tokens, {**attrs, "gen_ai.token.direction": "output"})


@contextmanager
def llm_span(
    operation: str,
    system: str,
    model: str,
    *,
    messages: Sequence | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Iterator[trace.Span]:
    """Open an LLM span with GenAI semantic attributes and record latency.

    Use only around code that does NOT ``yield`` to an SSE consumer (the current
    span is task-local). For streaming generators, manage a span manually.
    """
    start = time.perf_counter()
    with tracer.start_as_current_span(operation) as span:
        span.set_attribute("gen_ai.system", system)
        span.set_attribute("gen_ai.request.model", model)
        if temperature is not None:
            span.set_attribute("gen_ai.request.temperature", temperature)
        if max_tokens is not None:
            span.set_attribute("gen_ai.request.max_tokens", max_tokens)
        if messages is not None:
            set_prompt(span, messages)
        try:
            yield span
        finally:
            llm_latency.record(
                (time.perf_counter() - start) * 1000.0,
                {"gen_ai.system": system, "gen_ai.request.model": model},
            )


def setup_telemetry(app) -> None:
    """Install OTel trace/metric/log providers and auto-instrumentation.

    No-op (with a log line) when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OpenTelemetry disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return

    try:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry._logs import set_logger_provider

        from app.db import engine

        # Resource picks up OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES from env;
        # add a version + per-process instance id so deploys/replicas are distinguishable.
        resource = Resource.create(
            {
                "service.version": os.getenv("OTEL_SERVICE_VERSION", "0.1.0"),
                "service.instance.id": os.getenv("HOSTNAME") or str(uuid.uuid4()),
            }
        )

        # Traces
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)

        # Metrics
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
        )
        metrics.set_meter_provider(meter_provider)

        # Logs — route the standard logging tree to OTLP, stamped with trace_id.
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(logger_provider)
        otlp_log_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        logging.getLogger().addHandler(otlp_log_handler)
        # uvicorn configures its own loggers with propagate=False, so their request
        # logs never reach the root handler. Attach the OTLP handler directly so the
        # high-volume access/error logs also land in Loki.
        for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logging.getLogger(_name).addHandler(otlp_log_handler)
        LoggingInstrumentor().instrument(set_logging_format=True)

        # Auto-instrumentation. Exclude the Docker healthcheck endpoint so the
        # frequent /health polls don't flood traces and HTTP metrics.
        # exclude_spans drops the per-ASGI-event "http send"/"http receive"
        # spans — otherwise SSE streaming (/chat/stream) emits one span per
        # chunk, producing hundreds of spans that bury the meaningful ones.
        FastAPIInstrumentor.instrument_app(
            app, excluded_urls="health", exclude_spans=["receive", "send"]
        )
        SQLAlchemyInstrumentor().instrument(engine=engine)
        HTTPXClientInstrumentor().instrument()

        logger.info("OpenTelemetry enabled -> %s", endpoint)
    except Exception:  # pragma: no cover - never let telemetry break startup
        logger.exception("OpenTelemetry setup failed; continuing without telemetry")
