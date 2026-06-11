# TODO — Feature & quality roadmap

Plan drafted 2026-06-11, after the quests + world-ledger + UI-improvements work
landed. Replaces the previous best-practices TODO (everything in it shipped
except two small items, carried over into §5 below).

Stack reminder: **Vite + React SPA** + **FastAPI / SQLAlchemy async /
Postgres+pgvector**, 4 configurable LLM provider slots (Ollama-first).

---

## 1. Graduate the dark features (per-session toggles)

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

## 2. Unify the post-turn judge (one LLM call instead of three)

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

## 3. Continuity check for streaming

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

### 4a. Rewind & fork
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

### 4b. World sidebar fed by the ledger
The `WorldStateLedger` already tracks entities/inventory/threads/location as
JSON; `/session/{id}/world-state` already serves it. Render it: a live panel
(alongside `MemoryPanel`) showing location, inventory, known entities, open
threads. Pure frontend + maybe a leaner summary endpoint. Depends on §1 so
users can actually enable the ledger.

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

### 5a. LLM eval harness
Structural tests can't catch prompt/model quality drift. Small
golden-transcript suite + LLM-judge scoring for continuity, extraction
accuracy (memory/ledger/quests), and GM narration constraints. Runs locally
against real models on demand (`make eval` or a `pytest -m eval` marker
excluded from CI). Prerequisite for safely landing §2 and any prompt changes.

### 5b. Token/cost visibility
Per-turn token counts per provider slot (actor/memory/embedding/GM) as OTel
metrics in `app/telemetry.py`; panel in the Grafana RPG dashboard
(`observability/grafana/`). Quantifies what §2 saves.

### 5c. Carried over from the old TODO
- `ruff format` + `--check` in CI + `.pre-commit-config.yaml` (ruff + eslint);
  consider dropping the `E501` ignore.
- Narrow the broad `except Exception` blocks in
  `app/services/orchestrator.py` and the `get_session_memory` backfill in
  `app/main.py`.

---

## Suggested sequencing

1. **Quick wins (one sitting each):** 5c, §3 (retcon note).
2. **Phase 1:** §1 (toggles) → 4b (world sidebar) — the cheapest visible win
   once the ledger can be enabled, and it makes ledger output inspectable
   before §2 changes how it's extracted.
3. **Phase 2:** 5a (eval harness) → §2 (unified judge, validated by the evals)
   + 5b (measure the savings).
4. **Phase 3:** remaining §4 features as appetite dictates — 4a (fork) is the
   most distinctive; 4c/4d are nice-to-haves, cut first if time is short.

## Decisions (reviewed 2026-06-11)

All former open questions are resolved; details inline in each section above.

- **§3 continuity UX:** retcon note (invisible, next-turn self-correction);
  annotation-style SSE chip only as a metric-driven phase 2.
- **§4a rewind:** fork-only, never destructive.
- **§2 rollout:** behind `post_turn_judge_enabled` with the legacy path as
  fallback; delete legacy in a follow-up once evals pass.
- **§1 default-on:** bake first — toggles ship with globals off; flip defaults
  in a follow-up after real-session testing.
