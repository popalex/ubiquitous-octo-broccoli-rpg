# End-to-End OpenTelemetry Instrumentation — Reusable Plan

A portable recipe for adding **correlated, end-to-end observability** to a
web app: one trace that follows a user's click in the browser, through the
backend, down to DB queries and LLM/API calls — plus logs and metrics that
carry the same trace ID. Distilled from a FastAPI + React/Vite + LLM project;
the principles transfer to any HTTP frontend + backend.

## Core idea

Use **OpenTelemetry (OTel)** with **W3C trace-context propagation**:

1. The browser starts a trace and, on every API `fetch`, injects a
   `traceparent` header.
2. The backend's HTTP server instrumentation reads that header and makes its
   request span a **child of the browser span** — same trace ID across both
   processes.
3. Auto-instrumentation adds spans for DB queries and outbound HTTP (incl. LLM
   API calls); manual spans add semantic/business detail (LLM model, tokens,
   prompts; pipeline phases).
4. All three signals — **traces, logs, metrics** — export over OTLP to one
   backend. **Grafana LGTM** (`grafana/otel-lgtm`: Grafana + Tempo + Loki +
   Prometheus) is a single-container "one UI for everything"; Jaeger is a
   lighter traces-only alternative.

```
Browser ──(fetch + traceparent)──▶ Backend ──▶ DB / LLM
   │ trace spans                      │ same trace (continued via traceparent)
   └────────── OTLP ─────────────────┴──────────────▶ Grafana LGTM (Tempo/Loki/Prometheus)
```

## Decisions to make up front

- **Telemetry backend / viewer:** Grafana LGTM (traces+logs+metrics, one UI) vs
  Jaeger (traces only) vs hosted SaaS (Honeycomb/Datadog via OTLP).
- **Signals:** traces only, or traces + logs + metrics.
- **Sensitive content:** whether to put request bodies / LLM prompts &
  completions on spans (great for debugging, but stores content in telemetry).

## Part 1 — Telemetry backend (docker-compose)

```yaml
  otel-lgtm:
    image: grafana/otel-lgtm:latest
    ports:
      - "3000:3000"   # Grafana UI
      - "4317:4317"   # OTLP gRPC  (backend exporters)
      - "4318:4318"   # OTLP HTTP  (browser exporter, via same-origin proxy)
    volumes:
      - otel_lgtm_data:/data
```

On the backend service, set:
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-lgtm:4317`
- `OTEL_SERVICE_NAME=<your-backend>`
- `OTEL_RESOURCE_ATTRIBUTES=service.namespace=<app>,deployment.environment=local`

Grafana ships at `:3000` with Tempo/Loki/Prometheus datasources pre-wired.

## Part 2 — Backend (Python / FastAPI example)

**Dependencies** (current as of mid-2026; keep the `1.x` core and `0.xxbN`
instrumentation lines in lockstep — same release, e.g. core `1.42.x` ↔ instr
`0.63bN`):

```
opentelemetry-distro==0.63b1
opentelemetry-exporter-otlp==1.42.1
opentelemetry-instrumentation-fastapi==0.63b1
opentelemetry-instrumentation-sqlalchemy==0.63b1
opentelemetry-instrumentation-httpx==0.63b1     # covers OpenAI SDK (it uses httpx)
opentelemetry-instrumentation-logging==0.63b1
```

**`telemetry.py`** — one `setup_telemetry(app)` that:
- Gates on `OTEL_EXPORTER_OTLP_ENDPOINT` (no-op when unset → clean test runs).
- Sets `TracerProvider` + `BatchSpanProcessor(OTLPSpanExporter())`.
- Sets `MeterProvider` + `PeriodicExportingMetricReader(OTLPMetricExporter())`.
- Sets `LoggerProvider` + `BatchLogRecordProcessor(OTLPLogExporter())`, attaches
  a `LoggingHandler` to the root logger, and calls
  `LoggingInstrumentor().instrument(set_logging_format=True)` so existing
  `logger.*` calls flow to Loki stamped with `trace_id`/`span_id`.
- Calls auto-instrumentors: `FastAPIInstrumentor.instrument_app(app)`,
  `SQLAlchemyInstrumentor().instrument(engine=engine)`,
  `HTTPXClientInstrumentor().instrument()`.
- Wrap the whole body in `try/except` so telemetry can never break startup.

Also expose module-level helpers (bind to no-op providers until setup runs, so
safe to import anywhere): `tracer = trace.get_tracer(name)`, metric instruments
(`create_counter`/`create_histogram`), and a `llm_span(...)` context manager.

**Wire it:** call `setup_telemetry(app)` right after `app = FastAPI(...)`.

**Content flag:** gate prompt/completion capture behind an env var
(`OTEL_CAPTURE_CONTENT`, default your choice). Read it once at import
(`CAPTURE_CONTENT = env_bool(...)`) and route prompt/completion through
`set_prompt`/`set_completion` helpers that no-op when off — so you can flip
between **full** (prompts + responses on spans) and **metadata-only** (model,
tokens, latency) without code changes. Add it to `.env` and compose.

**Manual LLM spans** (in each provider call) using GenAI semantic conventions:
`gen_ai.system`, `gen_ai.request.model`, `.temperature`, `.max_tokens`,
`gen_ai.prompt`, `gen_ai.completion`, `gen_ai.usage.input_tokens` /
`output_tokens`; record token counters + a latency histogram.
- Non-streaming calls: a `start_as_current_span` context manager is fine.
- **Streaming generators:** the "current span" is task-local and leaks across
  `yield`. Use a **manual `start_span(...)` + `try/finally: span.end()`** and set
  `gen_ai.completion` from accumulated chunks. (For OpenAI streams, pass
  `stream_options={"include_usage": True}` to get token counts; for Ollama, read
  `prompt_eval_count`/`eval_count` from the final `done` chunk.)

**Pipeline phase spans + business attrs** in the orchestrator: wrap logical
phases (`retrieve`, `generate`, `persist`, `memory_refresh`, …) in
`start_as_current_span` so the trace reads like the app's pipeline. Safe only
around code that does **not** `yield` to an SSE consumer; in streaming handlers,
wrap the non-yielding awaited calls only and rely on provider spans for the rest.

## Part 3 — Frontend (React / TypeScript / Vite example)

**Dependencies** (current; `2.x` core line, `0.2xx` experimental line):

```
@opentelemetry/api ^1.9.0
@opentelemetry/sdk-trace-web ^2.7.1
@opentelemetry/sdk-trace-base ^2.7.1
@opentelemetry/context-zone ^2.7.1
@opentelemetry/resources ^2.7.1
@opentelemetry/instrumentation ^0.218.0
@opentelemetry/instrumentation-fetch ^0.218.0
@opentelemetry/exporter-trace-otlp-http ^0.218.0
@opentelemetry/semantic-conventions ^1.41.1
```

**`telemetry.ts`** — `setupTelemetry()`:
- `new WebTracerProvider({ resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "<frontend>" }), spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter({ url: `${base}/v1/traces` }))] })`.
- `provider.register({ contextManager: new ZoneContextManager() })` — keeps span
  context across `await`s.
- `registerInstrumentations({ instrumentations: [ new FetchInstrumentation({ propagateTraceHeaderCorsUrls: [/\/api\//] }) ] })` — **the linchpin**: auto-spans
  every `fetch` and injects `traceparent` on matching URLs.
- Export a `withUiSpan(name, attrs, fn)` helper that starts a span, runs `fn`
  inside `context.with(setSpan(...))`, and ends it — so any fetch inside becomes
  a child and the trace starts at the user's action.

**Init before render:** call `setupTelemetry()` at the top of the entry module
(`main.tsx`), before `createRoot`.

**User-action spans:** wrap key journeys (create/start, submit, delete, …) with
`withUiSpan("ui.<action>", {...}, () => api(...))`. Because all calls flow
through a central `api()`/`fetch` wrapper, the fetch instrumentation covers
100% of API traffic — including SSE streaming reads (the span stays open until
the stream ends, capturing time-to-last-chunk).

**Add `vite-env.d.ts`** declaring `import.meta.env` keys you read (e.g.
`VITE_OTEL_EXPORTER_OTLP_ENDPOINT`) so `tsc` passes.

## Part 4 — Avoid browser→collector CORS (important)

The browser's OTLP/HTTP exporter triggers a CORS preflight; the collector won't
have CORS enabled by default. **Cleanest fix:** export to a **same-origin path**
(e.g. `/otel`) and reverse-proxy it to the collector's `:4318`:
- **Vite dev:** add a `/otel` proxy → `http://localhost:4318` (rewrite strip
  `/otel`).
- **Prod nginx:** `location /otel/ { proxy_pass http://otel-lgtm:4318/; }`.

Set the exporter base URL to `/otel` (default) so it posts to
`/otel/v1/traces`. No CORS, works in dev and prod. (Alternative: enable CORS on
the collector's OTLP HTTP receiver.)

The backend's inbound `traceparent` must survive your API proxy — Vite's
`changeOrigin` and nginx `proxy_pass` forward headers by default, so no change
needed there; only add CORS allow-listing for `traceparent`/`tracestate` if the
browser ever calls the backend cross-origin directly.

## Verification

1. `docker compose up --build`; open Grafana `http://localhost:3000`.
2. Drive the key user flow in the app.
3. **Traces (Tempo):** the latest trace contains **both** `ui.*` (frontend) and
   server/DB/LLM spans under **one trace ID** → propagation works. LLM spans show
   model, tokens, prompt/completion.
4. **Logs (Loki):** backend `logger.*` lines appear with a `trace_id`; click →
   jumps to the trace.
5. **Metrics (Prometheus):** token/latency/request metrics have data.
6. Tests still pass (telemetry no-ops without the endpoint). Frontend build
   succeeds; devtools Network shows `traceparent` on API calls and OTLP posts to
   `/otel`.

## Gotchas checklist

- [ ] Regenerate the JS lockfile after editing `package.json` (a
  `--frozen-lockfile` Docker build fails otherwise).
- [ ] Keep OTel Python core (`1.x`) and instrumentation (`0.xxbN`) versions from
  the **same release**.
- [ ] Streaming = manual spans (`start_span`/`end`), not current-span context
  managers.
- [ ] Browser telemetry via same-origin proxy to dodge CORS.
- [ ] Gate `setup_telemetry` on the OTLP endpoint env var for clean test runs.
- [ ] Decide consciously whether prompts/PII go on spans.
