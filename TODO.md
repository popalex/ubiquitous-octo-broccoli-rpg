# TODO — Best-practice fixes

Backlog of improvements identified during a code review (2026-06-09). Ordered by
impact. Stack reminder: **Vite + React Router SPA** (not Next.js) + **FastAPI /
SQLAlchemy / Postgres+pgvector**.

---

## Tier 1 — Correctness (do first)

### 1. Sync DB calls block the event loop in `async def` routes
`app/db.py` yields a **sync** `Session`; every route in `app/main.py` is
`async def` and calls `db.query(...)` / `db.execute(...)` (~25 sync DB calls
across ~18 async routes). While one request waits on Postgres, the whole event
loop stalls — including SSE streaming to other clients.

Fix options, cheapest → cleanest:
- **a)** Wrap DB work in `fastapi.concurrency.run_in_threadpool`.
- **b)** Make DB-heavy non-streaming routes plain `def` (FastAPI auto-runs them
  in a threadpool).
- **c)** Migrate to `AsyncSession` + async psycopg (proper fix; biggest change;
  best for the streaming/orchestrator path in `app/services/orchestrator.py`).

### 2. `httpx.AsyncClient`s are never closed
Each provider opens an `AsyncClient` in `__init__`
(`app/providers/ollama_provider.py`, `app/providers/openai_provider.py`) via the
`@lru_cache` orchestrator singleton (`get_orchestrator`), but nothing calls
`aclose()`. Add a FastAPI **`lifespan`** handler that owns provider/client
startup + shutdown instead of lazy module-level construction. Bundle with #1.

### 3. No static type checker
Heavy type hints + Pydantic, but nothing verifies them. Add **mypy or pyright**
to `pyproject.toml` and the CI `lint` job. (Would have caught the `block`
NameError previously found in `_world_state_block`.) Highest value-per-effort.

---

## Tier 2 — Robustness & maintainability

### 4. React Error Boundary
No top-level boundary exists — any render error blanks the whole app. Add one
with a fallback UI around the router/app root (`frontend/src/main.tsx` /
`App.tsx`).

### 5. Introduce a data-fetching layer (TanStack Query or SWR)
Everything is raw `fetch` with manual `setIsBusy` / `setStatusText` / `useEffect`
(`frontend/src/api.ts`, `App.tsx`). A query lib gives caching/retries, removes
boilerplate, and would resolve the `set-state-in-effect` patterns we suppressed
in `frontend/eslint.config.js` — letting us **re-enable that rule**.

### 6. Break up `App.tsx`
~382 lines, ~20 `useState`s. Extract custom hooks (e.g. `useChatSession`,
`useSessionMemory`) and/or a reducer. Maintainability; riskiest file to touch.

### 7. Frontend tests
Backend has 127 tests; frontend has none. Add **Vitest + React Testing Library**
and wire into the `frontend` CI job (`.github/workflows/build-and-run-tests.yml`).

---

## Tier 3 — Polish

### 8. `ruff format` + pre-commit hook
Enable `ruff format` (add `ruff format --check .` to CI) and add a
`.pre-commit-config.yaml` running ruff + eslint so issues are caught before push,
not in CI. If adopting `ruff format`, consider dropping the `E501` ignore in
`pyproject.toml`.

### 9. CORS middleware
Only needed if the frontend is ever served cross-origin. Today the Vite proxy /
nginx make it same-origin, so this is latent, not urgent.

### 10. Narrow broad `except Exception`
Tighten the catch-all blocks in `app/services/orchestrator.py`
(`_extract_world_state`) and the backfill path in `app/main.py`
(`get_session_memory`) to the specific exceptions actually expected.

---

**Suggested starting point:** #3 (type checker) and #1 (async DB) materially
change reliability; #2 is small and naturally bundles with #1.
