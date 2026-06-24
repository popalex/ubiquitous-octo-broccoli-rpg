from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "openai", "mock"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "small-rpg-gpt"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/roleplay"

    # Dev mode: use a single model for all LLM tasks to save RAM
    dev_mode: bool = False
    dev_model_name: str = "llama3.2:3b"

    actor_provider: ProviderName = "ollama"
    memory_provider: ProviderName = "ollama"
    embedding_provider: ProviderName = "ollama"
    gm_provider: ProviderName = "ollama"

    actor_model_name: str = "llama3.2:8b"
    memory_model_name: str = "phi3:mini"
    embedding_model_name: str = "nomic-embed-text"
    gm_model_name: str = "llama3.2:8b"
    embedding_dimension: int = 768

    @model_validator(mode="after")
    def apply_dev_mode(self) -> Self:
        """In dev mode, override all LLM models to use a single model (saves RAM)."""
        if self.dev_mode:
            self.actor_model_name = self.dev_model_name
            self.memory_model_name = self.dev_model_name
            self.gm_model_name = self.dev_model_name
            # Increase timeout for model swapping on low-RAM systems
            if self.request_timeout_seconds < 180.0:
                self.request_timeout_seconds = 180.0
        return self

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"

    retrieval_top_k: int = 8
    retrieval_candidate_pool: int = 20
    recency_half_life_hours: int = 72
    memory_summary_interval: int = 6

    actor_max_input_tokens: int = 6000
    actor_reserved_output_tokens: int = 500
    actor_temperature: float = 0.7
    continuity_temperature: float = 0.2
    gm_temperature: float = 0.8
    gm_max_output_tokens: int = 800
    gm_narration_max_tokens: int = 0  # hard provider cap; 0 = no limit (avoids mid-word truncation)
    # Graceful length control: once narration passes this many tokens, stop at the
    # NEXT sentence boundary instead of cutting mid-word. 0 disables (truly unbounded).
    gm_narration_soft_limit_tokens: int = 1000
    request_timeout_seconds: float = 60.0

    # Default GM mode for new sessions: /session/init inherits it when the
    # request omits gm_enabled, and the UI seeds its toggle from /health.
    gm_enabled: bool = True

    # Suggested player responses: after each turn the post-turn judge proposes
    # 2-4 short next actions, shown as clickable chips (the free-text composer
    # stays). Chosen per-session at chronicle creation; /session/init inherits
    # this when the request omits suggestions_enabled, and the UI seeds its
    # toggle from /health. On by default after baking (TODO §1 follow-up).
    suggestions_enabled: bool = True
    suggestions_max: int = 4  # cap on chips offered per turn

    # GM event generation settings
    event_check_interval: int = 3  # Check for events every N turns
    event_probability: float = 0.4  # Base probability of event occurrence

    # World-state ledger: an authoritative, structured record of canon
    # (entities, inventory, threads, location, facts) injected as hard
    # constraints and updated every turn. On by default after baking
    # (TODO §1 follow-up); set the flag false to ship it dark again.
    world_state_enabled: bool = True
    world_state_max_entities: int = 30
    world_state_max_threads: int = 20
    world_state_max_facts: int = 40
    world_state_extract_max_tokens: int = 800

    # Quest system: AI-tracked narrative arcs (GM offers, emergent player
    # promises, escalation of neglected arcs). On by default after baking
    # (TODO §1 follow-up), like world_state. Turn-based knobs are in raw
    # turn_count units — GM mode advances turn_count by 2-3 per exchange, so
    # 12 turns is ~4-6 exchanges.
    quests_enabled: bool = True
    quest_max_active: int = 5  # cap of non-terminal quests tracked/injected
    quest_max_stages: int = 8  # per-quest stage cap
    quest_extraction_interval: int = 1  # run the post-turn judge every N turns
    quest_escalation_turns: int = 12  # turns without progress before escalation
    quest_extract_max_tokens: int = 700
    quest_temperature: float = 0.2

    # Dice / skill checks (§4c): in GM mode, when the player attempts something
    # with an uncertain outcome, the GM assesses a skill + difficulty (DC) and
    # the *server* rolls a d20 (auditable, persisted), then narration respects
    # the result. There is no character stat block — competence lives entirely
    # in the GM-chosen DC, surfaced to the player via the roll's rationale.
    # Outcomes are success / failure / critical_success (nat 20); there is no
    # critical-failure tier by design (a nat 1 is just a failure). Ships dark
    # behind this flag (bake-first, like world_state/quests did); GM-mode only.
    dice_enabled: bool = False
    dice_assess_max_tokens: int = 200  # cap on the GM action-assessment JSON call
    dice_assess_temperature: float = 0.2

    # Unified post-turn judge (§2): the per-turn world-state and quest extractions
    # are folded into ONE LLM call (PostTurnJudgeService) instead of two. Memory
    # (facts + episode summary) stays on its own cadence.
    post_turn_judge_max_tokens: int = 1100

    # Character sheet & progression (todo-rpg Phases 1+2): a per-chronicle sheet
    # of 4 flat-modifier attributes (MIGHT / FINESSE / WITS / PRESENCE). The d20
    # skill check rolls d20 + attribute_mod vs DC (DC = task difficulty), and
    # successful checks / quest completions grant XP that levels the character up
    # and bumps an attribute — deterministically (LLM proposes the attribute, the
    # engine does the math). Ships dark behind this flag (bake-first, like
    # world_state/quests/dice did). Requires dice_enabled to do anything visible.
    character_sheet_enabled: bool = False
    sheet_attribute_start: int = 1  # starting value of each attribute (a flat +N modifier)
    sheet_attribute_min: int = 0
    sheet_attribute_max: int = 6
    # XP grants. A successful check is the bread-and-butter source; criticals and
    # quest completions are worth more. A failed check still grants a sliver
    # ("you learn from failure") — set 0 to disable.
    xp_per_success: int = 10
    xp_per_critical: int = 20
    xp_per_failure: int = 1
    xp_per_quest_complete: int = 50
    # Level curve: level N (1-indexed) requires sheet_xp_curve_base * (N-1) cumulative
    # XP — i.e. a flat sheet_xp_curve_base per level. Tunable; see CharacterSheetService.
    sheet_xp_curve_base: int = 100

    # Resources & stakes (todo-rpg Phase 3): HP gives failure a cost. HP lives on
    # the character sheet, so it's active whenever CHARACTER_SHEET_ENABLED is on.
    # A failed *dangerous* check costs HP — the GM tags failure severity
    # (none/minor/major) and the engine applies a flat, deterministic amount (no
    # hallucinated numbers, mirroring how the DC band works). At 0 HP the character
    # is downed (a consequence) unless permadeath is on for the chronicle, in which
    # case the chronicle ends.
    sheet_hp_start: int = 20  # starting and maximum HP
    hp_damage_minor: int = 3
    hp_damage_major: int = 8
    # Rest heals a fraction of max HP (never a free full reset) and advances the
    # world by hp_rest_turn_cost turns, pushing neglected quests toward escalation —
    # so resting costs narrative ground rather than being spammable.
    hp_rest_heal_fraction: float = 0.5
    hp_rest_turn_cost: int = 3
    # Permadeath: chosen per chronicle at creation (NULL inherits this global).
    # Off → 0 HP downs the character (recoverable); on → 0 HP ends the chronicle.
    permadeath_enabled: bool = False

    @property
    def actor_context_budget(self) -> int:
        return max(512, self.actor_max_input_tokens - self.actor_reserved_output_tokens)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
