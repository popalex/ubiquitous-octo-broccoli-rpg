# Small RPG GPT

A self-hosted, local-first roleplay engine. You chat with an in-character actor while a Game Master narrates scenes and triggers events around you — backed by long-term vector memory so the world remembers what happened. Everything runs on small local LLMs through Ollama (OpenAI optional); nothing leaves your machine by default.

It's a full stack you can `docker compose up` and play: a React/Vite frontend, a FastAPI backend, and Postgres + pgvector for memory.

What makes it more than a chat wrapper:

- **Multiple cooperating models** — separate slots for the actor, the Game Master, memory/summarization, and embeddings, each independently configurable.
- **Long-term memory** — turns and extracted facts are vector-embedded; retrieval ranks them by `0.6·semantic + 0.25·recency + 0.15·importance`, and episodes are summarized as the chronicle grows.
- **Continuity checking** — a second model validates each reply against the world's canon and hard rules before it reaches you.
- **Full observability** — the whole stack is OpenTelemetry-instrumented; one trace follows a click from the browser down to the LLM call, viewable in a bundled Grafana.

Built with FastAPI, PostgreSQL, pgvector, Alembic, React/Vite, and Docker Compose.

Default mode is Ollama-first and Docker Compose runs Ollama inside the stack:

- Actor replies: Ollama (llama3.1:8b)
- Game Master (narration, events, NPCs): Ollama (llama3.1:8b)
- Memory extraction and summaries: Ollama (phi3:mini)
- Embeddings: Ollama (nomic-embed-text)
- OpenAI: optional fallback only

## Prerequisites

- Docker with Docker Compose v2
- [pnpm 11](https://pnpm.io/) for local frontend development outside Docker

## Stack

- Python 3.14
- FastAPI
- SQLAlchemy 2.x
- Alembic
- PostgreSQL 18 + pgvector
- Docker Compose
- Node 24
- pnpm 11 (frontend package manager)
- Ollama or OpenAI-compatible small models
- OpenTelemetry (end-to-end tracing, logs, metrics) → Grafana LGTM

## 1. Configure Environment

```bash
cp .env.sample .env
```

Defaults are already set up for Docker Compose to run Ollama locally in a container.

### Dev Mode (Single Model)

If you're low on RAM, enable dev mode to use a single smaller model for all LLM tasks:

```bash
DEV_MODE=true
DEV_MODEL_NAME=llama3.2:3b
```

This overrides actor, memory, and GM models to all use the same model.

### Production Mode (Multi-Model)

For best quality, use separate models optimized for each task:

- `ACTOR_MODEL_NAME=llama3.1:8b` - creative character dialogue
- `MEMORY_MODEL_NAME=phi3:mini` - precise fact extraction and summaries
- `GM_MODEL_NAME=llama3.1:8b` - world narration and events

Important:

- `OLLAMA_BASE_URL` should stay `http://ollama:11434` when the API runs inside Docker Compose.
- The first startup auto-pulls the configured models:
  - `llama3.1:8b` (actor + GM)
  - `phi3:mini` (memory)
  - `nomic-embed-text` (embeddings)
- In dev mode, only the single dev model + embeddings are pulled.

OpenAI is optional. If you want to switch providers later, set:

```bash
ACTOR_PROVIDER=openai
MEMORY_PROVIDER=openai
EMBEDDING_PROVIDER=openai
GM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
ACTOR_MODEL_NAME=gpt-4o-mini
MEMORY_MODEL_NAME=gpt-4o-mini
GM_MODEL_NAME=gpt-4o-mini
EMBEDDING_MODEL_NAME=text-embedding-3-small
EMBEDDING_DIMENSION=768
```

## 2. Start the Docker Dev Stack

```bash
docker compose up --build
```

Docker Compose automatically loads `docker-compose.override.yml` when it is present next to `docker-compose.yml`. In this project, that means `docker compose up --build` runs the frontend in Docker dev mode:

- builds the `dev` target from `Dockerfile.frontend`
- runs the Vite dev server with HMR
- bind-mounts `./frontend` into the container
- keeps container-managed dependencies in `/app/node_modules`
- exposes the frontend at `http://localhost:5173`
- proxies frontend `/api/*` requests to the `api` service

This starts:

- `postgres` on `localhost:5432`
- `ollama` on `localhost:11434`
- `api` on `localhost:8000`
- `frontend` on `localhost:5173`
- `otel-lgtm` (Grafana) on `localhost:3000`

The startup flow is:

1. PostgreSQL starts
2. Ollama starts
3. `ollama-init` pulls the configured small models automatically
4. The API runs `alembic upgrade head`
5. Uvicorn starts
6. The `pnpm` frontend dev server starts

The first boot can take several minutes because model downloads happen automatically.

Open the UI at:

```bash
http://localhost:5173
```

Useful dev commands:

```bash
docker compose ps
docker compose logs -f frontend api
docker compose down
```

To run the production nginx frontend instead of the Vite dev server, bypass the dev override:

```bash
docker compose -f docker-compose.yml up --build
```

This builds the `prod` target and serves the static app from nginx at:

```bash
http://localhost:8080
```

If you want to run the frontend outside Docker:

```bash
cd frontend
corepack enable
pnpm install
pnpm dev
```

Then open:

```bash
http://localhost:5173
```

## 3. Run Migrations Manually

```bash
docker compose exec api alembic upgrade head
```

## 4. Seed a Default Character and World

```bash
docker compose exec api python -m app.seed
```

## 5. Health Check

```bash
curl http://localhost:8000/health
```

The browser UI uses the Vite dev proxy, so it talks to the backend through `/api/*` while you browse `localhost:5173`.

## 6. Load or Update a Character

```bash
curl -X POST http://localhost:8000/character/load \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Guide Rowan",
    "description": "A calm scout-mage who speaks in precise sensory detail and never breaks character.",
    "hard_rules": [
      "Stay in character as Rowan.",
      "Do not mention being an AI or a model.",
      "Respect established canon and prior facts."
    ],
    "style_guide": "Grounded fantasy, observant, concise.",
    "world_name": "Glass Harbor",
    "world_description": "A storm-lashed port city built around old mirrored ruins.",
    "world_canon": "A blue lantern warns of incoming tide spirits. The harbor gates close at moonrise.",
    "world_hard_rules": [
      "The setting remains low-magic and dangerous.",
      "No instant travel or modern technology."
    ]
  }'
```

## 7. Start a Session

Use the `character_card_id` and `world_state_id` returned from `/character/load`.

```bash
curl -X POST http://localhost:8000/session/init \
  -H "Content-Type: application/json" \
  -d '{
    "character_card_id": "CHARACTER_ID",
    "world_state_id": "WORLD_ID",
    "title": "Harbor opening scene"
  }'
```

## 8. Chat

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID",
    "user_message": "Rowan, what do the blue lanterns mean tonight?"
  }'
```

## 9. Inspect Long-Term Memory

```bash
curl http://localhost:8000/session/SESSION_ID/memory
```

## Linting & Tests

Both run in CI on every pull request (`.github/workflows/build-and-run-tests.yml`).

**Backend (Python) — [Ruff](https://docs.astral.sh/ruff/):**

```bash
pip install -r requirements.txt   # ruff is included
ruff check .                      # lint
ruff check . --fix                # lint and auto-fix
pytest                            # tests (needs Docker running — testcontainers spins up Postgres+pgvector)
```

Ruff config lives in `pyproject.toml`.

**Frontend (TypeScript/React) — [ESLint](https://eslint.org/):**

```bash
cd frontend
pnpm install
pnpm lint        # ESLint
pnpm typecheck   # tsc -b (type errors only, no emit)
pnpm build       # typecheck + production build
```

ESLint config lives in `frontend/eslint.config.js`.

## Notes

- `MEMORY_SUMMARY_INTERVAL=6` means the system summarizes every 6 stored turns, which is 3 user/assistant exchanges.
- Hard rules are always included in the actor context packet.
- Retrieval ranking uses `score = 0.6 * semantic + 0.25 * recency + 0.15 * importance`.
- If first startup looks slow, check `docker compose logs -f ollama-init` to watch model pulls complete.
- If `/chat` returns a provider error, check `docker compose ps` and `docker compose logs ollama ollama-init api`.

## Observability (OpenTelemetry + Grafana)

The whole stack is instrumented with OpenTelemetry. A single **trace** follows
each user action from the browser → backend → database → LLM call, so you can
watch "user opens a new chronicle" all the way down to "Ollama generated this
reply" as one connected waterfall. Traces, logs, and metrics all ship to a
bundled **Grafana LGTM** container (Grafana + Tempo + Loki + Prometheus).

Open Grafana once the stack is up:

```bash
http://localhost:3000
```

- **Login:** `admin` / `admin`
- **Datasources:** Tempo (traces), Loki (logs), Prometheus (metrics) — pre-wired by the image.
- **Dashboards:** an **RPG** folder is auto-provisioned on startup with three
  ready-made dashboards (no setup needed):
  - **RPG · Metrics (LLM & HTTP)** — LLM tokens/sec & latency p95 by model,
    chat turns by mode, HTTP request p95 by route, avg memories retrieved.
  - **RPG · Logs** — backend log volume by level + a live log stream (click a
    line to jump to its trace via `trace_id`).
  - **RPG · Traces (OTel)** — recent traces, frontend `ui.*` user-action
    traces, and slow LLM spans; click any row for the full waterfall.

  These live in `observability/grafana/` and are mounted into the collector via
  docker-compose, so they survive restarts and are editable in the UI.

### How correlation works

The browser starts a trace and injects a W3C `traceparent` header on every
`/api` call; FastAPI continues that same trace server-side, and
SQLAlchemy/httpx/LLM spans hang off it. One trace ID ties it all together.

What you'll see in a single trace:

```
ui.new_chronicle / ui.send_chat        (frontend span — starts at the click)
└─ POST /api/...                        (fetch + traceparent)
   └─ POST /...                         (FastAPI server span, same trace)
      ├─ orchestrator.retrieve          → SELECT ... <=> embedding (pgvector)
      ├─ llm.generate_text              (model, tokens, prompt, completion)
      ├─ orchestrator.continuity_check
      └─ orchestrator.memory_refresh    → summary + embedding LLM calls
```

- **Logs (Loki):** existing backend logs are stamped with `trace_id` — click a
  log line to jump straight to its trace.
- **Metrics (Prometheus):** LLM token counts, LLM latency, chat turns, and
  retrieval sizes (`rpg_llm_tokens_total`, `rpg_llm_latency_*`, …), plus
  automatic HTTP request duration/throughput.

### Configuration

Set in `.env` (already in `.env.sample`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-lgtm:4317   # unset to fully disable telemetry
OTEL_SERVICE_NAME=rpg-backend
OTEL_RESOURCE_ATTRIBUTES=service.namespace=small-rpg-gpt,deployment.environment=local
OTEL_CAPTURE_CONTENT=true
```

- **`OTEL_CAPTURE_CONTENT=true`** — *full* telemetry: capture the actual LLM
  prompts/completions and user messages on spans (great for debugging RP
  quality).
- **`OTEL_CAPTURE_CONTENT=false`** — *metadata only*: model, token counts, and
  latency, with no prompt/response text stored.
- Leave `OTEL_EXPORTER_OTLP_ENDPOINT` unset (e.g. running the API outside
  Docker without the collector) and telemetry cleanly no-ops.

Browser telemetry is sent same-origin to `/otel` (proxied to the collector by
Vite in dev and nginx in prod) to avoid CORS — no extra setup needed.

## Game Master Mode

Enable GM mode when starting a session to get:

- **Scene narration** - atmospheric descriptions before/after character dialogue
- **Dynamic events** - random encounters, weather changes, NPC arrivals
- **NPC dialogue** - GM-controlled side characters
- **Scene transitions** - location and time changes with narrative bridges

GM mode settings:

```bash
GM_TEMPERATURE=0.8           # Higher for creative narration
GM_MAX_OUTPUT_TOKENS=800     # Longer for scene descriptions
EVENT_CHECK_INTERVAL=3       # Check for events every N turns
EVENT_PROBABILITY=0.4        # 40% chance when checked
```

The frontend UI has a GM toggle in the session setup form.
