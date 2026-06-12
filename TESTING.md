# TESTING.md — Test-coverage roadmap

Companion to `TODO.md` (feature roadmap). Drafted 2026-06-11.

## Where coverage stands

| Layer | State |
|---|---|
| Backend | ~175 pytest tests across 11 files, against real Postgres+pgvector (testcontainers), deterministic `MockProvider`, streaming paths covered. **Strong — no investment needed.** |
| Frontend unit | 23 Vitest tests: `api.test.ts`, `turns.test.ts`, `ErrorBoundary.test.tsx`, `chat.test.ts` (SSE streaming, both modes). No coverage of components or hooks yet. |
| Frontend CI | Lints + typechecks + runs `pnpm test`. |
| E2E | None. |
| LLM quality | None (see `TODO.md` §5a — eval harness; out of scope here). |

The gap is almost entirely frontend. More backend unit tests have low marginal
value; backend confidence problems are prompt/model drift, which the eval
harness addresses, not pytest.

## Priority order

### 1. Wire `pnpm test` into CI (one line, do first) — ✅ DONE

Turned out to be already wired: commit `16c8b65` (the Vitest-harness PR) added
a `pnpm test` step to the frontend CI job before this doc was drafted.

### 2. `chat.ts` unit tests (highest-value gap) — ✅ DONE (2026-06-12)

Shipped on `feature/roadmap-quick-wins` as `frontend/src/chat.test.ts`
(12 tests): every case below is covered, both stream modes.

`frontend/src/chat.ts` is ~334 lines — the largest frontend file — holding the
SSE parsing/state machine for both chat modes (`/chat/stream`,
`/gm/chat/stream`). A bug here breaks the core UX; it has zero tests and is
very testable.

Approach: mock `fetch` returning a `ReadableStream` of crafted SSE frames.
Cases to cover:
- happy path: `memories` → `phase` → `chunk`s → `done`, callbacks fire in
  order with accumulated text
- `event` frames (GM events) interleaved with chunks
- `error` frame mid-stream; stream aborts cleanly
- frames split across read boundaries / multiple frames in one read
- malformed JSON in a frame (skip, don't kill the stream)
- the documented invariant: **a failed post-stream refetch must not wipe the
  finished reply**
- abort/disconnect mid-stream

### 3. Component + hook tests (RTL + MSW)

Add `@testing-library/react` and `msw` (Vitest is already wired, setup in
`frontend/src/test/setup.ts`). Targets in value order:

1. `QuestJournal.tsx` — newest, most conditional rendering (stages, statuses,
   patch interactions against `/session/{id}/quests`).
2. `ChronicleHub.tsx` — session list, create/delete flows.
3. `ChatPanel.tsx` — message rendering, busy states, streamed-reply display.
4. `useSession.ts` / `useSessionMutations.ts` — TanStack Query cache behavior;
   invalidation after mutations is classic regression territory.

MSW mocks `/api/*` at the network level so hooks/components are tested through
the real `api.ts` wrapper, not stubbed functions.

### 4. Playwright smoke suite (thin — 4–6 tests, not a pyramid layer)

Flows: create chronicle → send message → streamed reply renders → open quest
journal → delete session.

- **Phase 1 — route-interception mode:** `page.route` mocks `/api/*`
  (including a scripted SSE body for the stream). Fast, deterministic, runs
  per-push in a new CI job (cache the browser install). Tests the real built
  frontend against a faked API.
- **Phase 2 (optional) — full-stack mode:** promote the test `MockProvider`
  out of `tests/conftest.py` into `build_provider("mock", ...)`
  (`app/providers/`), so `docker compose` can run the entire stack with
  canned LLM responses. Then a true frontend↔FastAPI↔Postgres smoke can run
  nightly or pre-release — not per-push. Only build this if phase 1 misses
  real integration bugs (e.g. SSE framing, proxy behavior).

## Non-goals

- Growing backend pytest coverage for its own sake (test #176 adds little).
- Visual-regression/screenshot testing.
- Asserting on real LLM output in any CI path — anything quality-related
  belongs to the eval harness (`TODO.md` §5a).

## Suggested sequencing

Steps 1–2 fit in one PR (`feature/frontend-stream-tests`). Step 3 can follow
incrementally, one component per PR alongside feature work (e.g. QuestJournal
tests with the §1 toggle UI from `TODO.md`). Step 4 phase 1 after 2–3 are in;
phase 2 only on demonstrated need.
