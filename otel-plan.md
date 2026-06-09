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

Grafana ships at `:3000` (login `admin`/`admin`) with Tempo (uid `tempo`),
Loki (uid `loki`) and Prometheus (uid `prometheus`) datasources **already
provisioned** by the image — reference those UIDs in dashboards.

**Auto-provision dashboards on startup** (the image ships only generic ones):
add a Grafana dashboard *provider* yaml + dashboard JSON files and bind-mount
them into the image's provisioning dirs:

```yaml
    volumes:
      - ./observability/grafana/provisioning/dashboards/app.yaml:/otel-lgtm/grafana/conf/provisioning/dashboards/app.yaml:ro
      - ./observability/grafana/dashboards:/otel-lgtm/grafana/dashboards/app:ro
```

Layout on disk:
```
observability/grafana/
  provisioning/dashboards/app.yaml     # the provider (folder, path, allowUiUpdates)
  dashboards/app-metrics.json          # Prometheus panels
  dashboards/app-logs.json             # Loki: log-volume timeseries + a logs panel
  dashboards/app-traces.json           # Tempo: traceql table panels
```

The provider yaml:
```yaml
apiVersion: 1
providers:
  - name: app
    folder: App                 # dashboards land in this Grafana folder
    type: file
    allowUiUpdates: true
    options:
      path: /otel-lgtm/grafana/dashboards/app   # must match the mount target
      foldersFromFilesStructure: false
```

In each dashboard panel set the target datasource to the **stable UID** (`{"type":"prometheus","uid":"prometheus"}`, `loki`, `tempo`). A practical 3-dashboard set:

- **Metrics** (Prometheus): `rate(<counter>_total[$__rate_interval])`,
  `histogram_quantile(0.95, sum by (le) (rate(<hist>_bucket[$__rate_interval])))`,
  and for HTTP latency a name-tolerant matcher
  `{__name__=~"http_server_(request_)?duration.*_bucket"}`.
- **Logs** (Loki): a volume timeseries `sum by (detected_level) (count_over_time({service_name="<svc>"}[$__interval]))`
  plus a `type:"logs"` panel querying `{service_name="<svc>"}`. (`service.name`
  becomes the `service_name` label via Loki's OTLP ingestion.)
- **Traces** (Tempo): `type:"table"` panels with targets
  `{"queryType":"traceql","query":"{}","tableType":"traces"}` (recent traces),
  and TraceQL filters like `{ name =~ "ui\\..*" }` or `{ duration > 2s }`.

**OTel→Prometheus name normalization** (this trips everyone): counters gain
`_total`, histograms gain `_bucket/_sum/_count`, and **units become name
suffixes** (`unit="ms"` → `..._milliseconds`, `unit="token"` → `..._tokens`).
Easiest fix: **omit `unit=` on custom instruments** for predictable names
(`app_llm_tokens_total`, `app_llm_latency_bucket`) and set display units on the
Grafana panel instead; or match with `{__name__=~"name.*_bucket"}`.

Verify provisioning cheaply by booting **just** the collector container and
querying Grafana's API (no full app needed):
```bash
docker compose up -d otel-lgtm
curl -s -u admin:admin "http://localhost:3000/api/datasources"          # tempo/loki/prometheus present?
curl -s -u admin:admin "http://localhost:3000/api/search?tag=<your-tag>" # dashboards loaded into the folder?
```

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
- **Attach the log handler to the server's own loggers too.** uvicorn (and
  gunicorn) configure `uvicorn`, `uvicorn.error`, `uvicorn.access` with
  **`propagate = False`**, so their request logs never reach the root handler —
  your Loki "logs" view ends up nearly empty (only your sparse `logger.*` calls
  show, not the `"POST /chat 200"` request lines). Fix:
  ```python
  for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
      logging.getLogger(name).addHandler(otlp_log_handler)
  ```
  (Exports only — console output is unchanged, no duplication.)
- Calls auto-instrumentors:
  `FastAPIInstrumentor.instrument_app(app, excluded_urls="health", exclude_spans=["receive", "send"])`,
  `SQLAlchemyInstrumentor().instrument(engine=engine)`,
  `HTTPXClientInstrumentor().instrument()`.
  - `excluded_urls="health"` — the frequent Docker healthcheck polls otherwise
    flood traces **and** the `http_server_*` metrics.
  - **`exclude_spans=["receive", "send"]`** — critical for **SSE / streaming
    endpoints**: the ASGI instrumentation emits one `http send` span *per
    streamed chunk*, so a single streaming response produces **hundreds** of
    spans that bury the meaningful ones (`orchestrator.*`, `llm.*`). Dropping
    them makes the trace readable. (The frontend→backend link still works —
    those send/receive spans were just noise children of the server span.)
- Wrap the whole body in `try/except` so telemetry can never break startup.
- Also exclude `/health` (and the OTLP export URL itself) on the **frontend**
  fetch instrumentation via `ignoreUrls: [/\/health$/, /\/otel\//]` — the health
  poll and self-tracing the exporter both pollute traces otherwise.

Also expose module-level helpers (bind to no-op providers until setup runs, so
safe to import anywhere): `tracer = trace.get_tracer(name)`, metric instruments
(`create_counter`/`create_histogram`), and a `llm_span(...)` context manager.

**Resource attributes:** add `service.version` (env `OTEL_SERVICE_VERSION`) and
`service.instance.id` (the container `HOSTNAME`, or a uuid) to the `Resource` so
deploys/replicas are distinguishable in queries.

**Mark failures as errors.** Spans opened with `start_as_current_span` (the
non-streaming `llm_span`, orchestrator phase spans) auto-record the exception and
set `STATUS=ERROR` when one propagates through them — even if an outer `except`
then swallows it, because the span's `__exit__` runs first. **Manual** spans
(`start_span` + `finally: end()`, used for streaming) do **not** — add
`except Exception as e: span.record_exception(e); span.set_status(Status(ERROR)); raise`.
Then failed turns are filterable in Tempo with `{ status = error }`.

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

## Troubleshooting (battle-tested)

### "Traces & metrics work but the logs dashboard is empty"
Two independent causes — check both, in this order:

1. **App logs never leave the process (code).** uvicorn's loggers have
   `propagate=False` (see Part 2). Confirm with a one-off: emit a log through the
   same OTLP setup and query Loki. If only your `logger.*` lines show and never
   the `"POST /... 200"` request lines, attach the handler to the `uvicorn*`
   loggers.

2. **The collector can't push to Loki (infra).** This presents *exactly* like a
   code bug — the exporter returns success to your app while logs vanish —
   because your app talks to the **collector** (`:4317`), and the
   **collector→Loki** hop is what fails. Diagnose with the collector's own
   self-metrics (scraped by the bundled Prometheus):
   ```bash
   curl -s -u admin:admin --get \
     "http://localhost:3000/api/datasources/proxy/uid/prometheus/api/v1/query" \
     --data-urlencode 'query={__name__=~"otelcol_(receiver_accepted|exporter_sent|exporter_send_failed)_log_records_total"}'
   ```
   - `receiver_accepted` climbing but `exporter_send_failed` climbing too ⇒ the
     collector receives your logs but **Loki rejects them**. (Traces/metrics keep
     working because Tempo/Prometheus are healthy — only Loki is sick.)
   - Probe Loki directly (it has `curl`, no `wget`):
     ```bash
     docker exec <otel-container> curl -s -XPOST \
       -H 'Content-Type: application/json' \
       -d '{"streams":[{"stream":{"job":"probe"},"values":[["'$(date +%s)'000000000","probe"]]}]}' \
       -o /dev/null -w '%{http_code}\n' http://localhost:3100/loki/api/v1/push
     ```
     `204` = ingester healthy; `500` with `rpc error: ... Ingester is shutting
     down` = Loki stopped accepting writes.

   - **See WHY** — Loki's logs are muted in this image (`logging=false`). Turn
     them on (and the collector's) to read the actual reason:
     ```yaml
     otel-lgtm:
       environment:
         ENABLE_LOGS_LOKI: "true"
         ENABLE_LOGS_OTELCOL: "true"
     ```
     then `docker compose up -d otel-lgtm && docker logs <otel-container>`.

   - **#1 real-world cause: a near-full disk.** Loki throttles/stops the ingester
     once the WAL filesystem crosses **90%** usage:
     `caller=wal.go:215 msg="disk usage exceeded threshold, throttling writes" usage_percent=90.5% threshold_percent=90.00%`.
     This presents exactly as "first logs work, then nothing." Check the host
     disk (`df -h /`) — note it's the **whole host disk**, not the tiny otel
     volume, that matters; local LLM models, other projects' images/volumes, and
     build cache are the usual hogs. Fix: free space below 90%
     (`docker image prune -af` reclaims unused images with no data loss;
     `docker system df` shows what's reclaimable), then
     `docker compose restart otel-lgtm`. Verify with the push probe (expect
     `204`) and a sustained loop. (Memory pressure / OOM is a *possible* but, in
     practice, less common cause — check `docker inspect --format '{{.State.OOMKilled}}'`
     and `docker stats` to rule it out; OOMKilled=false + low mem ⇒ it's the disk.)

### "Frontend and backend traces look disconnected"
Usually they're **not** — they share a trace ID but you're viewing it from the
backend side. Check, in order:

1. **Inspect a real trace's spans.** A connected trace has the frontend `ui.*` /
   `HTTP <METHOD>` span as root with the backend server span as its child
   (`parentSpanId` = the frontend span). Pull it from Tempo and list
   `service.name` + `name` + `spanId`/`parentSpanId` per span:
   ```bash
   curl -s -u admin:admin "http://localhost:3000/api/datasources/proxy/uid/tempo/api/traces/<id>"
   ```
   If both services appear under one root ⇒ it works; you were just opening the
   trace from the backend root (which hides the frontend parent). **Search Tempo
   by the frontend service** (`{ resource.service.name = "rpg-frontend" }`) to see
   the user-action root.
2. **If they're genuinely separate trace IDs**, the `traceparent` isn't reaching
   the backend. Bisect with curl — first confirm the **backend continues** a
   supplied header, then that your **proxy forwards** it:
   ```bash
   TP="00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01"
   curl -s -H "traceparent: $TP" http://localhost:8000/<endpoint>        # direct
   curl -s -H "traceparent: $TP" http://localhost:5173/api/<endpoint>    # via dev proxy
   # then GET /api/datasources/proxy/uid/tempo/api/traces/<the 32-hex id> — present?
   ```
   Backend continues but browser doesn't ⇒ the bug is browser-side: the web
   `FetchInstrumentation` isn't injecting. It injects for **same-origin**
   automatically; for cross-origin you must list the URL in
   `propagateTraceHeaderCorsUrls`. Confirm telemetry inits **before** the first
   fetch and that you didn't `ignoreUrls` the API path.
3. **A trace drowning in `http send` spans** (SSE/streaming) reads as "I can't
   see anything inside" — that's the `exclude_spans=["receive","send"]` fix, not
   a propagation problem. Remember streaming chat is **SSE over fetch**, not a
   websocket; OTel *does* capture the inner `orchestrator.*`/`llm.*` spans.

### Other quick checks
- **Loki `/api/v1/labels` returns nothing** without a time range — always pass
  `start`/`end` (ns) when querying via the API; an empty labels list is *not*
  proof that logs are missing.
- **Dashboard panels default to `now-1h`** — widen the range before concluding a
  panel is broken.
- **`force_flush()` vs `shutdown()` in throwaway test scripts:** a short-lived
  process can exit before `BatchSpanProcessor`/`BatchLogRecordProcessor` flushes.
  Call `force_flush()` (and a short sleep) before exit, or `shutdown()`. The
  long-running server flushes on its own schedule (~5s), so this only bites
  one-off diagnostics.

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
