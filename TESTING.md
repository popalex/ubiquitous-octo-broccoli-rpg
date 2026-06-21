# TESTING.md — Test-coverage roadmap

Companion to `TODO.md` (feature roadmap). Drafted 2026-06-11.

## Where coverage stands

| Layer | State |
|---|---|
| Backend | ~175 pytest tests across 11 files, against real Postgres+pgvector (testcontainers), deterministic `MockProvider`, streaming paths covered. **Strong — no investment needed.** |
| Frontend unit | 80 Vitest tests across lib (`api`, `turns`, `chat`, `suggestions`), components (`ChatPanel`, `ChronicleHub`, `QuestJournal`, `CodexPanel`, `ErrorBoundary`), and hooks (`useSession`, `useSessionMutations`) — RTL + MSW. |
| Frontend CI | Lints + typechecks + runs `pnpm test`. |
| E2E | None. |
| LLM quality | ✅ On-demand eval harness landed (`evals/`, `TODO.md` §5a, PR #34): 16 golden cases scoring continuity/memory/ledger/quests/GM against a real local model, `pytest -m eval` / `make eval`, excluded from CI. A CI-safe `MockProvider` plumbing self-test runs in the normal suite. Still out of scope for *this* doc (frontend-focused). |

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

### 3. Component + hook tests (RTL + MSW) — 🚧 bootstrapped (2026-06-14)

Harness landed via `feature/rewind-fork` (now merged to `main`):
`@testing-library/react` was already
present; **`msw` added** (dev dep; `msw: false` in `pnpm-workspace.yaml`
`allowBuilds` — its postinstall only generates the browser worker, unused by the
node `setupServer`). Shared server in `frontend/src/test/server.ts`, wired into
`frontend/src/test/setup.ts` (listen with per-test `resetHandlers`; only
*unhandled* `/api` calls error). First coverage shipped for the fork UI:
`ChatPanel.test.tsx` (fork-from-here button: visibility on persisted vs. live
turns, click payload, busy/disabled state) and `ChronicleHub.test.tsx` (fork
badge render + parent-link navigation via MSW-mocked `/api/sessions`).

Note: cards in `ChronicleHub` are themselves `role="button"`, so their
accessible name *contains* inner controls — query inner buttons by an exact
`aria-label`, not a substring/regex, to disambiguate.

Remaining targets in value order — ✅ all four landed (2026-06-19,
`feature/frontend-component-tests`; shared QueryClient render/`renderHook`
helper in `frontend/src/test/renderWithClient.tsx`):

1. ✅ `QuestJournal.tsx` — `QuestJournal.test.tsx` (9 tests): empty/null state,
   active/escalating/offered/concluded section sorting, hidden empty sections,
   escalating flag, stakes + stage done-state, concluded resolution, Abandon
   shown only on active arcs and PATCHing `status: abandoned` via MSW.
2. ✅ `ChronicleHub.tsx` — `ChronicleHub.test.tsx` (now 12 tests): list sort by
   `updated_at`, feature/turn badges, card navigation, empty state + create
   routing, delete flow (confirm/decline/failure-alert via mocked
   `window.confirm`/`alert`), error banner + retry (fork badge already done).
3. ✅ `ChatPanel.tsx` — `ChatPanel.test.tsx` (now 15 tests): message content +
   role labels, role/type classes, empty state, status text, composer
   send/typing, busy + no-session disabled states (fork + suggestion chips
   already done).
4. ✅ `useSession.ts` / `useSessionMutations.ts` — `useSession.test.ts` (8) +
   `useSessionMutations.test.ts` (4): query-key shape, enabled-gating
   (`useSessionDetail`/`useSessionSuggestions` idle when off), `retry: false`
   error surfacing, `useRefreshMemory` invalidating exactly memory/world-state/
   quests (not detail/turns) + stable callback identity, and
   `useStartSession`/`useForkSession` request bodies (at_turn variants) +
   error propagation.

MSW mocks `/api/*` at the network level so hooks/components are tested through
the real `api.ts` wrapper, not stubbed functions.

### 4. Playwright smoke suite (thin — 4–6 tests, not a pyramid layer)

Flows: create chronicle → send message → streamed reply renders → open quest
journal → delete session.

- **Phase 1 — route-interception mode — ✅ DONE (2026-06-19,
  `feature/playwright-smoke`).** `frontend/e2e/smoke.spec.ts` (6 tests): hub
  list, empty vault, create-chronicle journey, streamed reply, quest journal,
  delete. A single `page.route("**/api/**")` catch-all (`e2e/fixtures/mockApi.ts`)
  answers every call from an in-memory store, with the chat reply served as a
  scripted `text/event-stream` body — **no backend, Postgres, or Ollama; the
  "LLM" is the strings in the SSE frames.** `playwright.config.ts` builds +
  previews the real frontend; a new per-push `e2e` CI job installs only
  chromium. The mock is wired via an auto-fixture (`e2e/fixtures/test.ts`) and
  gated by `E2E_MODE` so the same specs run unchanged in Phase 2.
  - **Gotchas captured:** the chat stream is `POST /api/chat/stream` (session
    id in the body), *not* under `/session/:id`; an unmocked route returns 501
    → surfaces as the "Not Implemented" status string. `templates-extra.json`
    is gitignored, so CI uses base templates only (the create flow drives
    "Guide Rowan").
- **Phase 2 — full-stack contract mode — ✅ DONE (2026-06-21,
  `feature/e2e-phase2-mock-provider`).** Runs frontend ↔ real FastAPI ↔ Postgres
  with the **LLM faked at the backend**: `tests/conftest.py`'s test-only
  `MockProvider` was promoted into a real `build_provider("mock", …)` slot
  (`app/providers/mock_provider.py`) — deterministic canned reply (streamed
  word-by-word), hashed embeddings, and a benign superset `generate_json` that
  satisfies continuity + the post-turn judge (all consumers use `.get()`).
  `docker-compose.e2e.yml` is a **standalone** stack (postgres + api with all
  four provider slots = `mock` + the **Vite dev server** proxying `/api` to the
  api container) — **no Ollama, no Grafana/otel.** `E2E_MODE=live` +
  `E2E_BASE_URL` make the fixture skip browser interception.
  - **Design note (deviation from the original plan):** rather than re-running
    the Phase-1 specs verbatim, the live layer is a pair of dedicated
    self-contained specs (`frontend/e2e/live.spec.ts`, gated
    `E2E_MODE === "live"`), each creating a uniquely-titled chronicle and
    tearing down only its own data (safe on a shared, parallel-worker DB):
    1. **core journey** — create → send → streamed reply renders → persists in
       the hub → delete.
    2. **quest/world round-trip** — send a turn, then assert the post-turn
       judge's canned `quest_delta`/`world_delta` (from the mock provider) were
       applied server-side, persisted, refetched, and rendered: the quest "The
       Blue Lanterns" in the Journal and the NPC "The Harbormaster" in the
       Codex. This is the feature-level contract Phase 1 can only *fake*.

    The Phase-1 specs hardcode ids and assume pre-seeded sessions/quests that
    can't exist in a real DB, so `smoke.spec.ts` is gated to *skip* in live mode.
    Same flows and user-visible assertions, but reliable against the real
    contract.
  - **CI:** `.github/workflows/e2e-live.yml` (nightly cron + `workflow_dispatch`,
    not per-push) brings up the stack with `--wait`, runs the live specs, dumps
    logs + uploads the report on failure, and tears down with `down -v`.

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
