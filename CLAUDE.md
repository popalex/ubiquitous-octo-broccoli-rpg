# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A hybrid roleplay-chat app. A FastAPI backend orchestrates several small LLMs (Ollama-first, OpenAI optional) to drive an in-character actor, a Game Master, long-term memory, and continuity checks; a React/Vite frontend talks to it. Postgres + pgvector stores turns and vector-embedded memories.

## Commands

### Full stack (Docker)
```bash
docker compose up --build          # dev: Vite HMR frontend on :5173, api :8000, postgres :5432, ollama :11434, Grafana :3000
docker compose -f docker-compose.yml up --build   # prod: nginx static frontend on :8080 (bypasses the dev override)
docker compose exec api alembic upgrade head        # run migrations manually
docker compose exec api python -m app.seed          # seed default character + world
docker compose logs -f ollama-init                  # watch first-boot model pulls (can take minutes)
```
`docker-compose.override.yml` is auto-loaded by `docker compose up` and is what switches the frontend into Vite dev mode.

### Backend tests
```bash
pytest                       # all tests
pytest tests/test_world_state.py            # one file
pytest tests/test_api.py::test_name -v      # one test
```
Tests spin up a **real Postgres + pgvector** via `testcontainers`, so **Docker must be running locally** to run them. `pytest.ini` sets `asyncio_mode = auto` (no `@pytest.mark.asyncio` needed). `conftest.py` provides `db_session` (per-test transaction rolled back on exit, commits become savepoints), factory-boy factories, a deterministic `MockProvider`, and `async_client` fixtures — LLM calls never hit a real provider in tests.

### Frontend (outside Docker)
```bash
cd frontend && corepack enable && pnpm install
pnpm dev        # Vite dev server, proxies /api/* to the api service
pnpm build      # tsc -b && vite build
```

### Verify a change (run before pushing)
Run these to match what CI checks. CI lives in `.github/workflows/build-and-run-tests.yml`: it lints (ruff), lints+typechecks the frontend (ESLint + `tsc -b`), builds both Docker images, and runs `pytest` on Python 3.14.
```bash
# 1. Python lint (config in pyproject.toml)
ruff check .                 # add --fix to auto-fix

# 2. Backend tests (Docker must be running — uses testcontainers Postgres)
pytest

# 3. Frontend lint + typecheck (config in frontend/eslint.config.js)
cd frontend && pnpm install && pnpm lint && pnpm typecheck

# 4. Docker images build (same targets CI builds)
docker build -f Dockerfile.backend -t fa-backend .
docker build -f Dockerfile.frontend --target prod -t fa-frontend .
```
**Linters:** Ruff for Python (`E,F,I,UP,W,B`; `E501`/`B008` ignored — see `pyproject.toml`); ESLint for the frontend. The frontend deliberately uses react-hooks' stable rules and disables the new React-Compiler-era rules (`set-state-in-effect`, `no-useless-assignment`) that flag working code — see the comment in `eslint.config.js` before re-enabling.

### Migrations
Alembic config (`alembic.ini`) points at `localhost:5432`. Generate a revision after changing `app/models.py`:
```bash
docker compose exec api alembic revision --autogenerate -m "describe change"
docker compose exec api alembic upgrade head
```

## Architecture

### Request → orchestration flow
`app/services/orchestrator.py` (`OrchestratorService`) is the hub. A `/chat` or `/gm/chat` request runs:
1. **Retrieve** relevant memories (`RetrievalService`) + load recent turns.
2. **Build a context packet** — token-budgeted sections (canonical world state, hard rules/canon, recent turns, retrieved facts, episode summaries) assembled by `_build_context_packet` against `actor_context_budget`.
3. **Generate** the actor reply via the actor provider, using `ACTOR_SYSTEM_PROMPT`.
4. **Continuity check** (`ContinuityService`) — a second LLM validates the draft against hard rules/canon and may revise it. Failures are swallowed (turn still completes).
5. **Persist** user + assistant `Turn` rows, bump `session.turn_count`, commit.
6. **Post-turn (best-effort, never breaks the turn):** `MemoryService.maybe_refresh` and `WorldStateService.extract_and_apply`.

GM mode (`gm_chat`) wraps this with pre-narration (scene-setting), event triggering/generation, and post-narration. Streaming variants (`chat_stream`, `gm_chat_stream`) emit SSE events (`type: memories|phase|chunk|event|done|error`) and **skip the continuity check for speed**. The orchestrator is a singleton via `@lru_cache get_orchestrator()` — call `get_orchestrator.cache_clear()` when swapping settings/providers (tests do this).

### Providers (`app/providers/`)
`build_provider(name, model, settings)` returns an Ollama or OpenAI implementation of `BaseModelProvider` (`generate_text`, `generate_text_stream`, `embed_texts`, plus `generate_json` which parses JSON or raises `ProviderError`). **Four independent provider slots** — actor, memory, embedding, GM — each separately configurable by provider + model in `Settings`. `DEV_MODE=true` collapses actor/memory/GM to a single `DEV_MODEL_NAME` to save RAM.

### Memory model (`app/models.py`)
- `CharacterCard`, `WorldState` — reusable templates (static description, canon, hard rules) shared across sessions.
- `Session` — one chronicle; owns turns, memories, summaries, relationships, ledgers.
- `Turn` — every message; `turn_type` is `chat`/`gm_narration`/`gm_event`.
- `MemoryFact`, `EpisodeSummary` — vector-embedded (`Vector(EMBEDDING_DIMENSION)`); retrieval ranks them `0.6*semantic + 0.25*recency + 0.15*importance`. Summaries are produced every `MEMORY_SUMMARY_INTERVAL` turns.
- `WorldStateLedger` — **versioned, structured canon** (entities, inventory, threads, location, facts as JSON); each canon-changing turn writes a new immutable version row, latest = current. Distinct from the `WorldState` template. Gated behind `WORLD_STATE_ENABLED` (ships dark).
- `RelationshipState` — tracked source→target relationships.

`EMBEDDING_DIMENSION` is read from settings **at model-import time** — changing `EMBEDDING_DIMENSION` requires a migration of the `Vector` columns.

### Frontend (`frontend/src/`)
React 18 + react-router. `App.tsx` is the main stateful component; `api.ts` wraps fetch, `chat.ts` handles SSE streaming, `components/` holds the panels (Chat, Character, Codex, Memory, ChronicleHub). Character/world setup uses templates (`templates.ts` + `public/templates-extra.json`).

### Observability
The whole stack is OpenTelemetry-instrumented and ships traces/logs/metrics to a bundled Grafana LGTM container (:3000, admin/admin, RPG dashboards auto-provisioned from `observability/grafana/`). The browser starts a trace and injects a W3C `traceparent` on every `/api` call; FastAPI continues the same trace server-side. Backend telemetry helpers live in `app/telemetry.py` (`tracer`, metric instruments like `chat_turns`, `canon_size`); frontend in `src/telemetry.ts` (`withUiSpan`). Set `OTEL_EXPORTER_OTLP_ENDPOINT=""` to disable.

## Conventions
- All config is centralized in `app/config.py` `Settings` (pydantic-settings, loaded from `.env`). Add new tunables there; access via `get_settings()` (cached).
- Post-turn side effects (memory, world-state) are wrapped in try/except and must never fail a chat turn — preserve that.
- New DB-backed features: model in `app/models.py` → migration → pydantic schema in `app/schemas.py` → route in `app/main.py` → logic in a `app/services/` service.
