# RPG-depth roadmap

The direction (pinned 2026-06-22): this is **not** an MMO. It's a richer
**single-player** RPG. Build mechanical depth — progression, stats, items,
combat, factions — and drop MMO-scale infra (accounts/auth, shared-world
scoping, concurrency, realtime/presence, sharding).

## The core idea: close the loop

Today the app has **action resolution** (d20 skill checks, §4c / PR #65) and
**narrative consequences** (the `WorldStateLedger`), but the RPG loop is *open* —
nothing about the character persists mechanically and nothing improves. A chat
with dice is still a chat. A game is a closed loop:

```
character state → roll against it → consequences (HP / loot / XP)
      ↑                                                        │
      └──────────── progression changes the state ←───────────┘
```

Every phase below exists to close that loop, in dependency order.

## What already exists (build on these)

- **d20 skill checks** (`app/services/dice.py`, `game_master.assess_action`,
  `orchestrator._maybe_roll_skill_check`): GM judges DC from prose, rolls d20,
  injects a directive so prose respects the outcome. Persisted to `dice_rolls`,
  traced as `orchestrator.skill_check`. **Gap: the DC is invented per-turn and
  rolls against nothing persistent.**
- **`WorldStateLedger`**: versioned JSON canon — entities, inventory, threads,
  location, facts. Inventory exists but as freeform narrative strings.
- **`Quest`** + quest deltas (post-turn judge).
- **`RelationshipState`**: tracked source→target relationships.
- **Post-turn judge** (`PostTurnJudgeService`): one LLM call emits world-state /
  quest / suggestion deltas, applied independently. **This is the reusable
  machinery for XP/stat deltas too** — add new delta types, don't add new calls.
- **`CharacterCard`**: `description` / `hard_rules` / `style_guide` only — **no
  stats, no numbers.**

---

## Phase 1 — Character sheet (the keystone) ✅ SHIPPED

> Done (2026-06-24). `CharacterSheet` (MIGHT/FINESSE/WITS/PRESENCE flat
> modifiers + level + xp) keyed to `Session`, seeded at chronicle creation,
> copied on fork, behind `CHARACTER_SHEET_ENABLED` (on by default in compose,
> like quests/suggestions). The d20 check now rolls `d20 + attribute_mod vs DC`:
> the GM names the governing attribute and sets a task-difficulty-only DC; the
> sheet supplies competence. Read-only sheet panel + XP bar in the UI.

Persistent mechanical state for the character. Everything else depends on it.

- New stats/skills model (likely `CharacterSheet` keyed to `Session`, since
  progression is per-chronicle; the reusable `CharacterCard` template stays
  narrative). Start small: a handful of attributes (e.g. MIGHT / FINESSE / WITS /
  PRESENCE) + a few derived/named skills.
- **Retrofit the dice check** to roll `stat_or_skill_mod + d20 vs DC` instead of
  a bare d20. This is the payoff: the feature already shipped suddenly *means*
  something, and the GM sets DC for task difficulty while the sheet supplies
  competence (replacing today's "DC encodes competence from prose").
- Sheet visible/seeded in the creation flow + a sheet panel in the frontend.
- Pattern: model → migration → `schemas.py` → route in `main.py` → service.

**Smallest valuable version:** 4 attributes, the d20 check adds the relevant
modifier, sheet rendered read-only in the UI.

## Phase 2 — Progression / XP / leveling (makes it a game) ✅ SHIPPED

> Done (2026-06-24). XP from successful checks (+10), criticals (+20), a sliver
> on failures (+1, tunable), and quest completion (+50); flat 100-XP/level curve.
> Level-up bumps one attribute (the one the check used, else the lowest) and
> emits a "You reached level 2 / FINESSE increased to +6" beat — surfaced live
> (SSE) and persisted on the turn so it re-renders on reload. **Deviation from
> the plan below:** XP is granted **deterministically in the engine**
> (`_apply_progression` → `CharacterSheetService.grant_xp`, row-locked) rather
> than as a post-turn-judge delta — the engine already knows the check outcome,
> so no extra LLM call and no hallucinated math. The judge-delta path is still
> the right approach for *narrative-milestone* XP if that's added later.

Closes the loop: rolls → XP → better rolls.

- XP sources: successful checks, quest completion, encounters.
- Leveling curve raises attributes/skills (and later HP/resources).
- **Ride the post-turn judge**: emit an XP/advancement delta alongside the
  world/quest deltas already produced — no new LLM call.
- UI: XP bar, level-up moment, "you improved X" beat.

## Phase 3 — Resources & stakes (HP, etc.)

Failure needs a cost or rolls carry no tension.

- HP (and optionally stamina/mana, gold, consumables).
- Damage/healing as deltas; death/incapacitation handling that fits the
  single-player fiction (downed → consequence, not hard game-over necessarily).
- Stakes wire into the dice outcomes you already classify
  (success / failure / critical).

## Phase 4 — First-class items

Promote ledger inventory from strings to structured items with effects.

- Item model with properties + effects (a +1 lockpick lowers Sleight DCs; armor
  affects defense; a potion restores HP).
- Equip / use / consume; effects feed into Phase 1 modifiers and Phase 3
  resources.
- Migrate/coexist with the narrative inventory already in the ledger.

## Phase 5 — Encounters / combat

Where stats + dice + HP + items combine into structured multi-turn challenges.

- Rounds/initiative (or lighter "skill-challenge" framing if full combat is too
  heavy), enemy stat blocks, action economy.
- Reuses everything from Phases 1–4 — build it last so it isn't rebuilt.

## Phase 6 — Factions / world standing

The consequence flavor of RPG depth.

- Faction standing (extends the relationship machinery) that gates content and
  reacts to choices.
- Hooks into quests and world reactivity already present.

---

## Recommended first vertical slice (start here) ✅ SHIPPED 2026-06-24

> All four steps below are done — the loop is closed end-to-end and verified
> live (a successful FINESSE check leveled a chronicle up, with the attribute
> bump + beat). **Next up: Phase 3 (resources & stakes / HP).**

Don't build a phase at a time top-to-bottom — build a **thin vertical slice**
through Phases 1→2 first, so you get a playable "character who gets better" ASAP:

1. `CharacterSheet` with ~4 attributes, seeded at chronicle creation.
2. Dice check reads the relevant modifier: `d20 + mod vs DC`.
3. A success grants a little XP via a post-turn-judge delta; enough XP bumps an
   attribute.
4. Minimal UI: show the sheet + XP; surface "you leveled" in chat.

That's the smallest change that turns "chat with dice" into an RPG, and it makes
PR #65 the foundation instead of a one-off. Phases 3–6 then layer onto a spine
that already works.

## Foundational decisions (settled 2026-06-23)

These three cohere into one design: **light stats, per-chronicle, with the LLM as
proposer and the engine as authority.** They constrain every phase above.

- **System feel → custom-light.** ~4 attributes (e.g. MIGHT / FINESSE / WITS /
  PRESENCE), advantage-style, no SRD baggage. Rationale: the GM is an LLM —
  strong at narrative judgment, weak at faithfully bookkeeping a heavy ruleset.
  Light rules play to that and minimize hallucinated mechanics. (Not 5e-like.)
- **Stats live per-`Session`.** Progression is per-chronicle; `CharacterCard`
  stays a reusable *narrative* template. (A later "import a retired hero" is
  possible but explicitly not designed for now.)
- **LLM proposes, code applies.** The GM suggests deltas (XP +10, HP −3); the
  engine clamps and applies them deterministically. Mirrors the existing
  world/quest delta flow through the post-turn judge — no hallucinated math, and
  it reuses machinery instead of a parallel path.
