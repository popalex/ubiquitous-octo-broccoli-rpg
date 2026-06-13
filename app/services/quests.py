"""Quest service — AI-tracked narrative arcs.

Quests are text-RPG-shaped arcs (mysteries, promises, social arcs, moral
dilemmas, escalating threats), never fetch/kill checklists. They are born two
ways: GM plot-hook events become *offered* quests, and a post-turn LLM judge
detects *emergent* quests from commitments the player states in roleplay.

The same judge advances stages, flips offers to active when the player
engages, and resolves arcs. Quests neglected past a threshold are fed as
pressure into the GM event check so the world moves without the player.

All post-turn work is best-effort: failures are logged + metered, never
raised, so a quest hiccup can never break a chat turn. Invariants (terminal
immutability, stage flags never reverting, caps) are enforced in code, not
trusted to the model. Gated behind ``QUESTS_ENABLED``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from opentelemetry import trace
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_core.core_schema import ValidationInfo
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Quest
from app.models import Session as ChatSession
from app.prompts import QUEST_FROM_EVENT_PROMPT, QUEST_JUDGE_PROMPT
from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
from app.schemas import QuestStageSchema as QuestStage
from app.telemetry import quest_extract_failures, quest_updates, record_span_error, set_completion, tracer

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("rumored", "offered", "active", "escalating")
TERMINAL_STATUSES = ("completed", "failed", "abandoned")

QUEST_TYPES = ("mystery", "promise", "social", "dilemma", "threat")


# ---------------------------------------------------------------------------
# Delta schemas (what the judge returns)
# ---------------------------------------------------------------------------


# Column limits on the quests table (models.py); judge output is truncated to
# fit rather than rejected, so an over-long string can't sink a whole delta.
_FIELD_LIMITS = {"slug": 120, "title": 200}


class NewQuest(BaseModel):
    slug: str
    title: str
    quest_type: str = "promise"
    description: str
    stakes: str | None = None
    stages: list[QuestStage] = Field(default_factory=list)

    @field_validator("slug", "title", mode="before")
    @classmethod
    def _truncate_to_column_limit(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str):
            return value[: _FIELD_LIMITS[info.field_name or "slug"]]
        return value


class QuestUpdateItem(BaseModel):
    slug: str
    status: str | None = None
    stages_complete: list[str] = Field(default_factory=list)
    stages_add: list[QuestStage] = Field(default_factory=list)
    progress_note: str | None = None
    resolution: str | None = None


class QuestDelta(BaseModel):
    quests_new: list[NewQuest] = Field(default_factory=list)
    quests_update: list[QuestUpdateItem] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.quests_new or self.quests_update)


@dataclass(slots=True)
class QuestChange:
    """One applied quest change, for SSE notifications and responses."""

    quest: Quest
    change: str  # offered | started | advanced | escalated | completed | failed | abandoned
    detail: str | None = None


class QuestService:
    def __init__(
        self,
        judge_provider: BaseModelProvider,
        settings: Settings | None = None,
    ) -> None:
        self.judge_provider = judge_provider
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def load_open(self, db: AsyncSession, session_id: str) -> list[Quest]:
        """All non-terminal quests for a session, oldest first."""
        rows = await db.scalars(
            select(Quest)
            .where(Quest.session_id == session_id, Quest.status.in_(OPEN_STATUSES))
            .order_by(Quest.created_at.asc())
        )
        return list(rows.all())

    # ------------------------------------------------------------------
    # Inject
    # ------------------------------------------------------------------

    @staticmethod
    def render_block(quests: list[Quest]) -> str:
        """Render open quests as a compact prompt block for the actor/GM.

        Returns "" when there are no open quests so callers can skip injection.
        """
        if not quests:
            return ""
        lines = [
            "ACTIVE QUESTS — open story arcs; play toward them, but never resolve them for the player:",
        ]
        for quest in quests:
            next_stage = next((s.get("description") for s in quest.stages if not s.get("done")), None)
            label = "offered, not yet taken up" if quest.status in ("rumored", "offered") else quest.status
            bits = [f"- [{label}] {quest.title} ({quest.quest_type}) — {quest.description}"]
            if next_stage:
                bits.append(f"next: {next_stage}")
            if quest.stakes:
                bits.append(f"stakes: {quest.stakes}")
            lines.append("; ".join(bits))
        return "\n".join(lines)

    @staticmethod
    def render_pressure(quests: list[Quest]) -> str:
        """Render neglected quests for the GM event-check prompt ("" if none)."""
        if not quests:
            return ""
        return "\n".join(
            f"- {q.title} ({q.quest_type}): {q.description}" + (f" Stakes: {q.stakes}" if q.stakes else "")
            for q in quests
        )

    # ------------------------------------------------------------------
    # Delta application
    # ------------------------------------------------------------------

    def apply_delta(
        self,
        quests: list[Quest],
        delta: QuestDelta,
        *,
        turn_count: int,
        reserved_slugs: set[str] | None = None,
    ) -> list[QuestChange]:
        """Apply a judge delta to ORM quest objects, returning the changes.

        New quests are returned attached to the change list but NOT added to
        the db session — the caller persists them. ``reserved_slugs`` holds
        slugs of quests not in ``quests`` (terminal ones) that the unique
        constraint still covers. Invariants enforced here (not trusted to the
        model):
        - terminal quests are immutable;
        - "escalating"/"rumored"/"offered" are never settable by the model;
        - stage ``done`` flags never revert; stages merge by id, capped;
        - new quests are skipped past the open cap or on duplicate slugs.
        """
        changes: list[QuestChange] = []
        by_slug = {q.slug: q for q in quests}
        taken_slugs = set(by_slug) | (reserved_slugs or set())
        open_count = sum(1 for q in quests if q.status in OPEN_STATUSES)

        for update in delta.quests_update:
            quest = by_slug.get(update.slug)
            if quest is None or quest.status in TERMINAL_STATUSES:
                continue
            change_kind = "advanced"

            # Copy the stage dicts: in-place mutation would also mutate the
            # ORM-committed value, so SQLAlchemy would see "no change" and
            # skip the UPDATE on the JSON column.
            existing_stages = [dict(s) for s in (quest.stages or [])]
            stage_ids = {s.get("id") for s in existing_stages}
            stages_changed = False
            for stage in update.stages_add:
                if stage.id in stage_ids or len(existing_stages) >= self.settings.quest_max_stages:
                    continue
                existing_stages.append({"id": stage.id, "description": stage.description, "done": False})
                stage_ids.add(stage.id)
                stages_changed = True
            if update.stages_complete:
                complete = set(update.stages_complete)
                for existing in existing_stages:
                    if existing.get("id") in complete and not existing.get("done"):
                        existing["done"] = True
                        stages_changed = True
            quest.stages = existing_stages

            status_changed = False
            new_status = (update.status or "").strip().lower()
            if new_status and new_status != quest.status:
                if new_status == "active" and quest.status in ("rumored", "offered", "escalating"):
                    quest.status = "active"
                    if quest.accepted_turn is None:
                        quest.accepted_turn = turn_count
                    change_kind = "started"
                    status_changed = True
                elif new_status in TERMINAL_STATUSES:
                    quest.status = new_status
                    quest.resolved_turn = turn_count
                    quest.resolution = update.resolution or update.progress_note or "Concluded."
                    change_kind = new_status
                    status_changed = True
                    open_count -= 1  # frees a slot for quests_new in this same delta
                # Anything else (escalating, rumored, offered, unknown) is
                # reserved for code-driven transitions — ignore it.

            # Only real changes count as progress: an update carrying nothing
            # but a slug (or an ignored status) must not reset the neglect
            # clock, or the judge could keep quests from ever escalating.
            if not (stages_changed or status_changed or (update.progress_note or "").strip()):
                continue

            # Progress of any kind un-escalates and resets the neglect clock.
            if quest.status == "escalating":
                quest.status = "active"
            quest.last_progress_turn = turn_count
            changes.append(
                QuestChange(quest=quest, change=change_kind, detail=update.progress_note or update.resolution)
            )

        for new in delta.quests_new:
            if new.slug in taken_slugs or open_count >= self.settings.quest_max_active:
                continue
            quest_type = new.quest_type if new.quest_type in QUEST_TYPES else "promise"
            quest = Quest(
                slug=new.slug,
                title=new.title,
                quest_type=quest_type,
                description=new.description,
                stakes=new.stakes,
                status="active",  # emergent quests are player commitments — already engaged
                origin="emergent",
                stages=[
                    {"id": s.id, "description": s.description, "done": False}
                    for s in new.stages[: self.settings.quest_max_stages]
                ],
                created_turn=turn_count,
                accepted_turn=turn_count,
                last_progress_turn=turn_count,
            )
            by_slug[new.slug] = quest
            taken_slugs.add(new.slug)
            open_count += 1
            changes.append(QuestChange(quest=quest, change="started", detail=new.description))

        return changes

    # ------------------------------------------------------------------
    # Extract (after the turn)
    # ------------------------------------------------------------------

    async def extract_and_apply(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        response_text: str,
        turn_id: str | None = None,
    ) -> list[QuestChange]:
        """Run the post-turn quest judge and persist its delta.

        Best-effort: provider/schema failures are logged + metered and return
        an empty list — never raised."""
        if session.turn_count % self.settings.quest_extraction_interval != 0:
            return []
        with tracer.start_as_current_span("orchestrator.quest_extract") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            quests, reserved_slugs = await self.load_open_and_reserved(db, session)
            open_json = [
                {
                    "slug": q.slug,
                    "title": q.title,
                    "quest_type": q.quest_type,
                    "description": q.description,
                    "status": q.status,
                    "stages": q.stages,
                }
                for q in quests
            ]
            user_content = (
                f"OPEN QUESTS:\n{open_json}\n\nLATEST EXCHANGE:\nPLAYER: {user_message}\nRESPONSE: {response_text}"
            )
            try:
                payload = await self.judge_provider.generate_json(
                    [
                        ProviderMessage(role="system", content=QUEST_JUDGE_PROMPT),
                        ProviderMessage(role="user", content=user_content),
                    ],
                    temperature=self.settings.quest_temperature,
                    max_tokens=self.settings.quest_extract_max_tokens,
                )
            except ProviderError as exc:
                logger.exception("quest judge failed for session=%s", session.id)
                quest_extract_failures.add(1, {"reason": "provider"})
                record_span_error(span, exc)
                return []

            try:
                delta = QuestDelta.model_validate(payload)
            except ValidationError as exc:
                logger.warning("quest delta invalid for session=%s: %s", session.id, exc)
                quest_extract_failures.add(1, {"reason": "schema"})
                record_span_error(span, exc)
                return []

            return await self.apply_quest_delta(
                db, session, delta, quests=quests, reserved_slugs=reserved_slugs, turn_id=turn_id
            )

    async def load_open_and_reserved(self, db: AsyncSession, session: ChatSession) -> tuple[list[Quest], set[str]]:
        """Load open quests (for the judge) plus the reserved terminal slugs.

        One query: open quests go to the judge, while terminal slugs are
        reserved so a judge that reuses a concluded quest's slug can't trip the
        unique constraint and sink the delta."""
        all_quests = (
            await db.scalars(select(Quest).where(Quest.session_id == session.id).order_by(Quest.created_at.asc()))
        ).all()
        quests = [q for q in all_quests if q.status in OPEN_STATUSES]
        reserved_slugs = {q.slug for q in all_quests if q.status not in OPEN_STATUSES}
        return quests, reserved_slugs

    async def apply_quest_delta(
        self,
        db: AsyncSession,
        session: ChatSession,
        delta: QuestDelta,
        *,
        quests: list[Quest],
        reserved_slugs: set[str] | None = None,
        turn_id: str | None = None,
    ) -> list[QuestChange]:
        """Apply an already-extracted quest delta and persist its changes.

        Shared by the legacy ``extract_and_apply`` and the unified post-turn
        judge so the invariants, slug reservation, and persistence stay
        single-sourced. Sets attributes on the current span; best-effort
        (failures logged + metered, never raised)."""
        span = trace.get_current_span()
        if delta.is_empty():
            span.set_attribute("rpg.quest.delta.empty", True)
            return []

        changes = self.apply_delta(quests, delta, turn_count=session.turn_count, reserved_slugs=reserved_slugs)
        if not changes:
            return []
        for change in changes:
            # New quests come out of apply_delta without a session.
            if change.quest.session_id is None:
                change.quest.session_id = session.id
                change.quest.source_turn_id = turn_id
                db.add(change.quest)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("quest write conflict for session=%s; skipping", session.id)
            quest_extract_failures.add(1, {"reason": "conflict"})
            record_span_error(span, exc)
            return []
        except SQLAlchemyError as exc:
            # e.g. DataError from oversized judge output — roll back so the
            # request's session isn't left in an aborted transaction.
            await db.rollback()
            logger.warning("quest write failed for session=%s: %s", session.id, exc)
            quest_extract_failures.add(1, {"reason": "db"})
            record_span_error(span, exc)
            return []

        for change in changes:
            quest_updates.add(1, {"change": change.change})
        span.set_attribute("rpg.quest.changes", len(changes))
        set_completion(span, delta.model_dump_json())
        logger.info(
            "quest_extract session=%s changes=%s",
            session.id,
            [(c.quest.slug, c.change) for c in changes],
        )
        return changes

    # ------------------------------------------------------------------
    # GM plot-hook offers
    # ------------------------------------------------------------------

    async def offer_from_event(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        event_seed: str,
        description: str,
        turn_id: str | None = None,
    ) -> Quest | None:
        """Structure a GM plot-hook event into an ``offered`` quest.

        Best-effort: returns ``None`` on provider failure, invalid payload,
        duplicate slug, or when the open-quest cap is reached."""
        open_count = await db.scalar(
            select(func.count())
            .select_from(Quest)
            .where(Quest.session_id == session.id, Quest.status.in_(OPEN_STATUSES))
        )
        if (open_count or 0) >= self.settings.quest_max_active:
            return None

        world_context = ""
        if session.world_state is not None:
            world_context = f"{session.world_state.name}: {session.world_state.description}"
        prompt = QUEST_FROM_EVENT_PROMPT.format(
            event_seed=event_seed,
            description=description,
            world_context=world_context or "Unknown world.",
        )
        try:
            payload = await self.judge_provider.generate_json(
                [ProviderMessage(role="user", content=prompt)],
                temperature=self.settings.quest_temperature,
                max_tokens=self.settings.quest_extract_max_tokens,
            )
            new = NewQuest.model_validate(payload)
        except (ProviderError, ValidationError) as exc:
            logger.warning("quest offer skipped for session=%s: %s", session.id, exc)
            quest_extract_failures.add(1, {"reason": "offer"})
            return None

        existing = await db.scalar(select(Quest).where(Quest.session_id == session.id, Quest.slug == new.slug))
        if existing is not None:
            return None

        quest = Quest(
            session_id=session.id,
            slug=new.slug,
            title=new.title,
            quest_type=new.quest_type if new.quest_type in QUEST_TYPES else "mystery",
            description=new.description,
            stakes=new.stakes,
            status="offered",
            origin="gm_event",
            stages=[
                {"id": s.id, "description": s.description, "done": False}
                for s in new.stages[: self.settings.quest_max_stages]
            ],
            created_turn=session.turn_count,
            last_progress_turn=session.turn_count,
            source_turn_id=turn_id,
        )
        db.add(quest)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.warning("quest offer conflict for session=%s slug=%s", session.id, new.slug)
            return None
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.warning("quest offer write failed for session=%s: %s", session.id, exc)
            quest_extract_failures.add(1, {"reason": "db"})
            return None
        quest_updates.add(1, {"change": "offered"})
        logger.info("quest_offer session=%s slug=%s", session.id, quest.slug)
        return quest

    # ------------------------------------------------------------------
    # Player-driven transitions
    # ------------------------------------------------------------------

    @staticmethod
    async def abandon(db: AsyncSession, session: ChatSession, quest: Quest) -> Quest:
        """Player-driven terminal transition, mirroring apply_delta's terminal
        branch so manual and judge-driven conclusions stay shaped alike."""
        quest.status = "abandoned"
        quest.resolved_turn = session.turn_count
        quest.resolution = "Abandoned by the player."
        quest.last_progress_turn = session.turn_count
        await db.commit()
        await db.refresh(quest)
        quest_updates.add(1, {"change": "abandoned"})
        return quest

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    async def neglected(self, db: AsyncSession, session: ChatSession) -> list[Quest]:
        """Active/escalating quests with no progress for quest_escalation_turns,
        throttled so the same quest doesn't escalate every check."""
        threshold = self.settings.quest_escalation_turns
        quests = await db.scalars(
            select(Quest).where(
                Quest.session_id == session.id,
                Quest.status.in_(("active", "escalating")),
                Quest.last_progress_turn <= session.turn_count - threshold,
                Quest.last_escalation_turn <= session.turn_count - threshold,
            )
        )
        return list(quests.all())

    async def mark_escalating(self, db: AsyncSession, session: ChatSession, quests: list[Quest]) -> list[QuestChange]:
        """Flag quests as escalating after a consequence event fired for them."""
        changes: list[QuestChange] = []
        for quest in quests:
            quest.status = "escalating"
            quest.last_escalation_turn = session.turn_count
            changes.append(QuestChange(quest=quest, change="escalated", detail=quest.stakes))
        if changes:
            await db.commit()
            quest_updates.add(len(changes), {"change": "escalated"})
        return changes

    @staticmethod
    async def throttle_pressure(db: AsyncSession, session: ChatSession, quests: list[Quest]) -> None:
        """Stamp the escalation clock after a pressure-driven event check that
        did NOT produce a consequence event. Without this, the same neglected
        quests would bypass the GM event probability gate on every subsequent
        check, forcing an event-check LLM call (and event pressure) each time."""
        if not quests:
            return
        for quest in quests:
            quest.last_escalation_turn = session.turn_count
        await db.commit()
