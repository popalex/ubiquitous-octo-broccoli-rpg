# TODO — Feature & quality roadmap

Plan drafted 2026-06-11, after the quests + world-ledger + UI-improvements work
landed. Replaces the previous best-practices TODO (everything in it shipped
except two small items, carried over into §5 below).

Stack reminder: **Vite + React SPA** + **FastAPI / SQLAlchemy async /
Postgres+pgvector**, 4 configurable LLM provider slots (Ollama-first).

---

## 1. Graduate the dark features (per-session toggles) — ✅ DONE (2026-06-12)

Shipped on `feature/roadmap-quick-wins`: nullable `Session` overrides +
migration, `app/services/features.py` resolution (override → global), flags
accepted by `/session/init` and returned resolved in init/list/detail, UI
toggles in chronicle creation, per-session state in the summary bar, hub-card
badges. Per the bake-first decision the globals still ship `false` —
**flipping the defaults after real-session baking remains a follow-up.**
Follow-up shipped 2026-06-12: the UI toggles (incl. a new global GM default,
`GM_ENABLED`) now seed from the compose-provided globals via `/health`;
an explicit user choice in localStorage still wins.

**Problem:** `world_state_enabled` and `quests_enabled` are env-level flags
defaulting to `false` — the two flagship features are invisible unless you edit
`.env` and restart. They should be choices made when creating a chronicle.

**Plan:**
- Add nullable boolean overrides to `Session` (`world_state_enabled`,
  `quests_enabled` in `app/models.py`) + Alembic migration. `NULL` = inherit
  the global setting, so existing sessions keep current behavior.
- Resolution helper (session override → global setting) used by
  `OrchestratorService`, `WorldStateService`, `QuestService` instead of reading
  `settings.*_enabled` directly.
- Expose the flags in `SessionInitRequest` / session responses
  (`app/schemas.py`), accept them in `/session/init`.
- UI: toggles in the chronicle-creation flow (`CodexSetup.tsx` /
  `ChronicleHub.tsx`); show feature state in the session header.
- **Decision (2026-06-11): bake first.** Ship the toggles with globals still
  `false`, play a few real chronicles with both features on (post-turn cost on
  small local models is the main unknown), then flip the global defaults to
  `true` in a follow-up.

**Effort:** small-medium. **Risk:** low (additive, defaults preserve behavior).

## 2. Unify the post-turn judge (one LLM call instead of three) — ✅ SHIPPED behind flag (2026-06-13, PR #41)

Shipped on `feature/post-turn-judge` (PR #41): `PostTurnJudgeService`
(`app/services/post_turn_judge.py`) makes one `generate_json` call validated
into a typed `TurnJudgment`, gated behind `post_turn_judge_enabled` with the
legacy two-call path (`maybe_refresh` + `extract_and_apply`) intact as fallback
in `OrchestratorService._run_post_turn`. Backend tests + eval parity target
landed (commit `28ab9e7`); dashboard panels added (`6b2d26a`).
**Follow-up remaining:** (a) ✅ default flipped on (2026-06-14, `feature/post-turn-judge-default-on`)
— `app/config.py` default `True`, prod compose + `.env.sample` to `true` (dev
override was already on); full suite green (225) with the new default; (b) **delete the
legacy path** once this bakes on `main` (per the "flag, then delete" decision below).

**Problem:** every turn fires up to three post-turn LLM calls — memory refresh
(`MemoryService.maybe_refresh`), world-state extraction
(`WorldStateService.extract_and_apply`), quest judge (`QuestService`). On small
local models that's heavy latency/RAM churn, and the three extractions read the
same recent turns yet never share results (quest entities and ledger entities
are disconnected).

**Plan:**
- New `PostTurnJudgeService` exposing `judge_turn(...) -> TurnJudgment`, a
  pydantic schema with typed sections (`memory_facts`, `world_delta`,
  `quest_updates`). Internally it makes one call to the providers' existing
  generic `generate_json` primitive and validates the raw payload into
  `TurnJudgment` immediately — callers never touch untyped JSON, and each
  section can be rejected independently if malformed.
- Prompt sections assembled dynamically from the enabled flags (with §1, a
  session with quests off simply omits that section).
- Apply each section through the existing services' apply paths, each wrapped
  in its own try/except — one bad section must not sink the others, and the
  whole judge stays best-effort (never fails the turn — repo convention).
- Cross-link while applying: quest-related entities reference ledger entities.
- Episode summaries (`MEMORY_SUMMARY_INTERVAL`) stay a separate periodic call.
- Settings: reuse the memory provider slot.
- **Decision (2026-06-11): flag, then delete.** Ship behind
  `post_turn_judge_enabled` with the legacy three-call path intact as
  fallback; once the eval harness (§5a) and a few real sessions confirm
  quality, delete the legacy path in a follow-up PR.
- Tests: extend `MockProvider` scripting for the combined payload; port the
  relevant cases from `test_memory.py` / `test_world_state.py` /
  `test_quests.py`.

**Effort:** medium. **Risk:** medium (extraction quality on small models with a
bigger combined schema — needs real-model spot-checking, see §5 eval harness).

## 3. Continuity check for streaming — ✅ DONE (2026-06-12)

Shipped on `feature/roadmap-quick-wins`: post-stream `ContinuityService` run in
both stream paths, violations persisted as `Turn.retcon_note` (new migration),
injected into the next context packet as a required "Continuity Corrections"
section, `rpg.continuity.revisions` counter added. Phase-2 annotation chip not
built (metric-driven, as decided).

**Problem:** `chat_stream` / `gm_chat_stream` skip the continuity check
entirely for speed — and streaming is the primary UX path, so the continuity
feature mostly never runs.

**Plan:**
**Decision (2026-06-11): retcon note.** Visible-revision SSE rejected for now:
it rewrites text the user already read, races their next message, and requires
mutating already-committed `Turn` rows (persist happens before post-turn).

- Run `ContinuityService` *after* the stream completes, inside the post-turn
  phase (it already has the full reply text there).
- On contradiction, persist a **retcon note** on the turn and inject it into
  the next context packet as a hard constraint, so the GM/actor self-corrects
  narratively next turn.
- Keep it best-effort (failures swallowed, turn already persisted); add a
  `continuity_revisions` counter metric in `app/telemetry.py`.
- Possible phase 2, only if the metric shows frequent/severe violations: an
  **annotation-style** SSE event (expandable "continuity note" chip under the
  reply — never text replacement).

**Effort:** small. **Risk:** low.

## 4. Gameplay-loop features

In rough value order; each is independently shippable.

### 4a. Rewind & fork — ✅ DONE (2026-06-14, merged to `main` via `feature/rewind-fork`)
Backend: `sessions.parent_session_id` + `forked_at_turn` columns (migration
`b1c2d3e4f5a6`), `ForkService` (`app/services/fork.py`) doing a *full-fidelity*
copy (turns ≤ N, derived facts/summaries, relationships, the ledger version
current at N → new version 1, quests created ≤ N, with turn-id remapping;
embeddings copied verbatim), `POST /session/{id}/fork?at_turn=N` (omit `at_turn`
to fork the whole chronicle), lineage fields on session list/detail responses,
`rpg.session.forks` metric + Grafana panel, and `tests/test_fork.py` (7 tests).
Frontend: hover "Fork from here" on each persisted turn (`ChatPanel` →
`useForkSession`, navigates to the new chronicle) and a "Fork @ N" badge on
forked chronicles in `ChronicleHub` linking to the parent. (Fork affordances
use lucide-react `GitFork` icons after the icon-library migration — the old
`⑂` glyph rendered blank in Firefox on Linux.)

Every `Turn` is persisted and the ledger is versioned — the data model already
supports time travel.
- API: `POST /session/{id}/fork?at_turn=N` — copy session row, turns ≤ N,
  memories/summaries derived from them, and the ledger version current at N.
- UI: "fork from here" on a turn in the chronicle view; forks listed in
  `ChronicleHub` with a parent link.
- **Decision (2026-06-11): fork-only.** No destructive rewind — the original
  chronicle is never altered, avoiding cascade deletes across turns, memories,
  summaries, and ledger versions. Revisit only if forking proves clumsy for
  the "fix a bad turn" case.

### 4b. World sidebar fed by the ledger — ✅ DONE (already shipped)
Turned out to be already built: `CodexPanel.tsx` (landed with the world-state
work, polished in the ui-improvements PR) renders location, dramatis personae,
the fallen, inventory, open threads, and canon facts from `useWorldState`, and
`useRefreshMemory` invalidates the query after every streamed turn — so it is
live. With §1's toggles users can now actually enable it. Added
`CodexPanel.test.tsx` (2026-06-12) to pin the rendering. The "leaner summary
endpoint" idea was a *maybe* and is skipped until the full payload proves
heavy.

### 4c. Dice / skill checks
Lightweight d20 texture for GM mode, not a combat engine.
- Server rolls (auditable, persisted on the turn) when the GM model requests a
  check; new SSE event `type: roll`; UI renders an animated roll chip.
- GM prompt addition: when an action's outcome is uncertain, emit a check
  request (skill, DC) instead of narrating success.

### 4d. Chronicle export
Turns + episode summaries → clean Markdown (chapters from summaries, dialogue
from turns). `GET /session/{id}/export?format=md`, download button in the UI.
EPUB later if Markdown proves useful.

## 5. Quality & ops

### 5a. LLM eval harness — ✅ DONE (2026-06-13)
Shipped on `feature/eval-harness` (PR #34): a top-level `evals/` package — 16
golden cases across continuity, memory, world-state, quests, and GM narration —
that runs the **real prompts from `app/prompts.py`** against a live local model
and scores each case structurally (binary signals) or with a pass/fail LLM judge
(reserved for prose constraints; small models flap on it for anything
structurally checkable). Marked `eval` and excluded from the default/CI run via
`addopts = -m "not eval"`; opt in with `pytest -m eval` or `make eval`. Skips
cleanly when no model is reachable; a CI-safe plumbing self-test
(`MockProvider`) runs in the normal suite. Validated 15/16 → 16/16 on
`llama3.2:3b`.

Its first finding was acted on immediately (PR #35,
`feature/world-state-noop-guard`): on description-only turns the world-state
extractor over-extracted (phantom inventory decrements, narration→facts) and
churned a new ledger version every turn. Fixed with a hardened
`WORLD_STATE_EXTRACT_PROMPT` + an apply-side material-change guard in
`extract_and_apply` (skips the version write when the applied ledger is
unchanged; meters `rpg.canon.noop_deltas`). This is the prerequisite for safely
landing §2 and any prompt changes — **now unblocked.**

### 5b. Token/cost visibility — ✅ DONE (2026-06-12)
Shipped on `feature/roadmap-quick-wins`: providers carry a `slot` label
(actor/memory/embedding/gm, threaded through `build_provider` — distinct even
in DEV_MODE where the slots share a model name), attached to the
`rpg.llm.tokens` metric (`rpg.slot` attribute) and to LLM spans. Two new
Grafana panels: tokens/sec by slot, and avg tokens per chat turn by slot —
the yardstick for what §2 saves.

### 5c. Carried over from the old TODO — ✅ DONE (2026-06-12)
- ~~`ruff format` + `--check` in CI + `.pre-commit-config.yaml` (ruff + eslint);
  consider dropping the `E501` ignore.~~ Done; `E501` ignore dropped too. Note:
  ruff `target-version` pinned to `py312` so the formatter doesn't emit
  PEP 758 syntax the local 3.12 venvs can't parse (see `pyproject.toml`).
- ~~Narrow the broad `except Exception` blocks in
  `app/services/orchestrator.py` and the `get_session_memory` backfill in
  `app/main.py`.~~ Done where the failure mode is identifiable (DB-only
  queries → `SQLAlchemyError`; backfill → `RuntimeError`/`ProviderError`/
  `SQLAlchemyError`). The post-turn guards stay deliberately broad — the
  never-fail-the-turn convention — and are commented as such.

---

## Suggested sequencing

1. **Quick wins (one sitting each):** 5c ✅, §3 (retcon note) ✅.
2. **Phase 1:** §1 (toggles) ✅ → 4b (world sidebar) ✅ — the cheapest visible win
   once the ledger can be enabled, and it makes ledger output inspectable
   before §2 changes how it's extracted.
3. **Phase 2:** 5a (eval harness) ✅ → §2 (unified judge) ✅ shipped behind flag
   + 5b ✅ (measure the savings) + default flipped on ✅. **← next: let it bake on
   `main`, then delete the legacy two-call path.**
4. **Phase 3:** remaining §4 features as appetite dictates — 4a (fork) ✅ shipped;
   4c/4d are nice-to-haves, cut first if time is short.

## Decisions (reviewed 2026-06-11)

All former open questions are resolved; details inline in each section above.

- **§3 continuity UX:** retcon note (invisible, next-turn self-correction);
  annotation-style SSE chip only as a metric-driven phase 2.
- **§4a rewind:** fork-only, never destructive.
- **§2 rollout:** behind `post_turn_judge_enabled` with the legacy path as
  fallback; delete legacy in a follow-up once evals pass.
- **§1 default-on:** bake first — toggles ship with globals off; flip defaults
  in a follow-up after real-session testing.
