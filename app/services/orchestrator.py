from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings, get_settings
from app.models import DiceRoll, Turn
from app.models import Session as ChatSession
from app.prompts import ACTOR_SYSTEM_PROMPT
from app.providers.base import ProviderError, ProviderMessage, build_provider
from app.schemas import (
    ChatResponse,
    DiceRollResult,
    GMChatResponse,
    GMEventGenerateResponse,
    QuestUpdateNotification,
    RetrievedMemoryItem,
)
from app.services.character_sheet import CharacterSheetService
from app.services.context_packet import (
    ContextPacketBuilder,
    continuity_canon,
    estimate_tokens,
    hard_rules_text,
    recent_turns_text,
)
from app.services.continuity import ContinuityResult, ContinuityService
from app.services.dice import CRITICAL_SUCCESS, FAILURE, SUCCESS, message_may_need_check, roll_check, roll_directive
from app.services.features import character_sheet_on, dice_on, items_on, permadeath_on, quests_on, world_state_on
from app.services.game_master import GameMasterService
from app.services.items import ItemChange, ItemService
from app.services.memory import MemoryService
from app.services.post_turn_judge import PostTurnJudgeService
from app.services.post_turn_runner import PostTurnRunner
from app.services.quests import QuestChange, QuestService
from app.services.retrieval import RetrievalService
from app.services.turn_persister import TurnPersister
from app.services.world_state import WorldStateService
from app.telemetry import chat_turns, continuity_revisions, dice_rolls, retrieval_selected, tracer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE frame emitters
# ---------------------------------------------------------------------------
# Typed helpers for the Server-Sent Events the stream entry points emit. The
# wire shape (`data: {json}\n\n`, the `type` discriminator, field names) is the
# contract the frontend dispatches on (see frontend/src/chat.ts); centralizing
# it here keeps every frame in lock-step and kills format-typo bugs.


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def sse_chunk(content: str) -> str:
    return _sse({"type": "chunk", "content": content})


def sse_phase(phase: str) -> str:
    return _sse({"type": "phase", "phase": phase})


def sse_pre_narration_chunk(content: str) -> str:
    return _sse({"type": "pre_narration_chunk", "content": content})


def sse_pre_narration_error(error: str) -> str:
    return _sse({"type": "pre_narration_error", "error": error})


def sse_event(event: object) -> str:
    return _sse({"type": "event", "event": event})


def sse_roll(roll: dict) -> str:
    return _sse({"type": "roll", "roll": roll})


def sse_quest_update(quest: dict) -> str:
    return _sse({"type": "quest_update", "quest": quest})


def sse_suggestions(suggestions: list[str]) -> str:
    return _sse({"type": "suggestions", "suggestions": suggestions})


def sse_advancement(advancement: list[str]) -> str:
    return _sse({"type": "advancement", "advancement": advancement})


def sse_done(session_id: str) -> str:
    return _sse({"type": "done", "session_id": session_id})


def sse_error(error: str) -> str:
    return _sse({"type": "error", "error": error})


# Shown when a permadeath chronicle has ended (status="dead") and the player
# tries to act again. Forking from an earlier turn is the way to continue.
_DEAD_CHRONICLE_MSG = (
    "This chronicle has ended — your hero has fallen. Fork from an earlier turn to continue their story."
)


class OrchestratorService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.actor_provider = build_provider(
            self.settings.actor_provider, self.settings.actor_model_name, self.settings, slot="actor"
        )
        self.memory_provider = build_provider(
            self.settings.memory_provider, self.settings.memory_model_name, self.settings, slot="memory"
        )
        self.embedding_provider = build_provider(
            self.settings.embedding_provider, self.settings.embedding_model_name, self.settings, slot="embedding"
        )
        self.gm_provider = build_provider(
            self.settings.gm_provider, self.settings.gm_model_name, self.settings, slot="gm"
        )
        self.retrieval = RetrievalService(self.embedding_provider, self.settings)
        self.memory = MemoryService(self.memory_provider, self.embedding_provider, self.settings)
        self.continuity = ContinuityService(self.memory_provider)
        self.game_master = GameMasterService(self.gm_provider, self.settings)
        self.world_state = WorldStateService(self.memory_provider, self.settings)
        self.quests = QuestService(self.memory_provider, self.settings)
        self.character_sheet = CharacterSheetService(self.settings)
        self.items = ItemService(self.settings)
        self.post_turn_judge = PostTurnJudgeService(
            self.memory_provider, self.world_state, self.quests, self.items, self.settings
        )
        self.post_turn = PostTurnRunner(self.memory, self.post_turn_judge)
        self.turns = TurnPersister(estimate_tokens)
        self.context = ContextPacketBuilder(self.settings)

    async def aclose(self) -> None:
        """Close every provider's HTTP client. Dedupes by identity because
        DEV_MODE collapses the actor/memory/GM slots onto one instance."""
        seen: set[int] = set()
        for provider in (self.actor_provider, self.memory_provider, self.embedding_provider, self.gm_provider):
            if id(provider) in seen:
                continue
            seen.add(id(provider))
            await provider.aclose()

    async def chat(self, db: AsyncSession, session_id: str, user_message: str) -> ChatResponse:
        session = await db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        if session.status == "dead":
            return ChatResponse(
                session_id=session.id,
                reply=_DEAD_CHRONICLE_MSG,
                continuity_applied=False,
                continuity_issues=[],
                retrieved_memories=[],
            )

        retrieved = await self.retrieval.retrieve(db, session, user_message)
        recent_turns = (
            await db.scalars(
                select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
            )
        ).all()
        recent_turns = list(reversed(recent_turns))

        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self.context.build(session, recent_turns, retrieved, world_state_block, quest_block)
        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=hard_rules_text(session.character_card, session.world_state),
        )
        draft_reply = await self.actor_provider.generate_text(
            [
                ProviderMessage(role="system", content=system_prompt),
                ProviderMessage(role="user", content=f"{context_packet}\n\nCurrent user message:\n{user_message}"),
            ],
            temperature=self.settings.actor_temperature,
            max_tokens=self.settings.actor_reserved_output_tokens,
        )

        try:
            continuity = await self.continuity.validate(
                hard_rules=hard_rules_text(session.character_card, session.world_state),
                world_canon=continuity_canon(session, world_state_block),
                recent_transcript=recent_turns_text(recent_turns),
                user_message=user_message,
                draft_reply=draft_reply,
            )
        except ProviderError:
            logger.exception("continuity check skipped for session=%s", session.id)
            continuity = ContinuityResult(final_reply=draft_reply, applied=False, issues=[])

        assistant_turn = await self.turns.persist_chat_turns(
            db,
            session,
            user_message=user_message,
            assistant_content=continuity.final_reply,
            continuity_notes="\n".join(continuity.issues) if continuity.issues else None,
        )

        await self.post_turn.refresh_memory(db, session)
        quest_changes, suggestions, item_changes = await self.post_turn.judge(
            db,
            session,
            user_message=user_message,
            response_text=continuity.final_reply,
            turn_id=assistant_turn.id,
        )
        advancement = await self._apply_progression(db, session, None, quest_changes, assistant_turn, item_changes)
        logger.info(
            "chat session=%s turn_count=%s continuity_applied=%s", session.id, session.turn_count, continuity.applied
        )

        return ChatResponse(
            session_id=session.id,
            reply=continuity.final_reply,
            continuity_applied=continuity.applied,
            continuity_issues=continuity.issues,
            quest_updates=self._quest_change_notifications(quest_changes),
            suggestions=suggestions,
            advancement=advancement,
            retrieved_memories=[
                RetrievedMemoryItem(
                    id=item.id,
                    kind=item.kind,
                    content=item.content,
                    weighted_score=item.weighted_score,
                    semantic_score=item.semantic_score,
                    recency_score=item.recency_score,
                    importance=item.importance,
                )
                for item in retrieved
            ],
        )

    async def _maybe_roll_skill_check(
        self, db: AsyncSession, session: ChatSession, user_message: str
    ) -> tuple[DiceRollResult | None, str]:
        """Assess the player's action and, if its outcome is uncertain, roll a
        d20 server-side (§4c). Returns ``(roll_result_or_None, directive)`` where
        ``directive`` is injected into the GM/actor context so the prose respects
        the roll. GM-mode only, gated by ``dice_on``. Best-effort — any failure
        yields no roll and never breaks the turn (repo convention)."""
        with tracer.start_as_current_span("orchestrator.skill_check") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            enabled = dice_on(session, self.settings)
            span.set_attribute("rpg.dice.enabled", enabled)
            if not enabled:
                return None, ""
            # Skip the per-turn assessment LLM call on messages that plainly can't
            # need a check (questions / non-actions) — assess_action is the costly
            # part of the feature, so this keeps dialogue turns cheap.
            may_need = message_may_need_check(user_message)
            span.set_attribute("rpg.dice.prefiltered", not may_need)
            if not may_need:
                return None, ""
            # Character sheet (todo-rpg Phase 1): when present, the GM names the
            # governing attribute and we add its modifier; the DC becomes
            # task-difficulty-only. No sheet → modifier 0, original behavior.
            sheet = None
            if character_sheet_on(session, self.settings):
                sheet = await self.character_sheet.load_for_session(db, session.id)
            try:
                assessment = await self.game_master.assess_action(db, session, user_message, sheet=sheet)
            except Exception:
                logger.exception("skill-check assessment failed for session=%s", session.id)
                span.set_attribute("rpg.dice.assess_failed", True)
                return None, ""
            span.set_attribute("rpg.dice.requires_check", assessment.requires_check)
            if not assessment.requires_check:
                return None, ""
            modifier = self.character_sheet.attribute_mod(sheet, assessment.attribute)
            # First-class items (todo-rpg Phase 4): equipped check_bonus gear adds
            # to the roll for the governing attribute.
            if items_on(session, self.settings):
                items = await self.items.load_for_session(db, session.id)
                item_bonus = self.items.check_bonus_for(items, assessment.attribute)
                span.set_attribute("rpg.dice.item_bonus", item_bonus)
                modifier += item_bonus
            die, total, outcome = roll_check(assessment.dc, modifier)
            dice_rolls.add(1, {"outcome": outcome})
            span.set_attribute("rpg.dice.skill_label", assessment.skill_label)
            span.set_attribute("rpg.dice.dc", assessment.dc)
            span.set_attribute("rpg.dice.die", die)
            span.set_attribute("rpg.dice.attribute", assessment.attribute or "")
            span.set_attribute("rpg.dice.modifier", modifier)
            span.set_attribute("rpg.dice.total", total)
            span.set_attribute("rpg.dice.stakes", assessment.stakes or "")
            span.set_attribute("rpg.dice.outcome", outcome)
            result = DiceRollResult(
                skill_label=assessment.skill_label,
                dc=assessment.dc,
                die=die,
                attribute=assessment.attribute,
                modifier=modifier,
                total=total,
                stakes=assessment.stakes,
                outcome=outcome,
                rationale=assessment.rationale or None,
            )
            return result, roll_directive(assessment.skill_label, assessment.dc, die, outcome, modifier)

    async def _persist_dice_roll(
        self, db: AsyncSession, session: ChatSession, roll: DiceRollResult, turn_id: str | None
    ) -> None:
        """Persist a resolved roll for audit + transcript re-render. Best-effort.

        Commits its own write (like the other post-turn services): the turns were
        already committed by ``persist_gm_turns``, and ``get_db`` never commits on
        its own — a bare flush here would be discarded when the request session
        closes. ``expire_on_commit=False`` keeps ``session`` usable afterward."""
        try:
            db.add(
                DiceRoll(
                    session_id=session.id,
                    turn_id=turn_id,
                    skill_label=roll.skill_label,
                    dc=roll.dc,
                    rationale=roll.rationale,
                    die=roll.die,
                    attribute=roll.attribute,
                    modifier=roll.modifier,
                    total=roll.total,
                    stakes=roll.stakes,
                    outcome=roll.outcome,
                )
            )
            await db.commit()
        except SQLAlchemyError:
            logger.exception("dice roll persist failed for session=%s", session.id)
            await db.rollback()

    async def _apply_progression(
        self,
        db: AsyncSession,
        session: ChatSession,
        roll: DiceRollResult | None,
        quest_changes: list[QuestChange],
        assistant_turn: Turn,
        item_changes: list[ItemChange] | None = None,
    ) -> list[str]:
        """Surface this turn's mechanical beats and persist them on
        ``assistant_turn`` so a chronicle reload re-renders them (mirrors how a
        resolved roll is re-attached on /turns). Covers item gains/losses
        (todo-rpg Phase 4, sheet-independent), then sheet XP/level-ups (Phase 2)
        and HP damage/downed/death (Phase 3) when the sheet is on. Best-effort —
        any failure yields what beats were already collected."""
        advancement: list[str] = []
        # Item beats first — items can be enabled without the character sheet.
        for change in item_changes or []:
            advancement.append(change.notification())

        if character_sheet_on(session, self.settings):
            try:
                # Checks grant XP tagged with the attribute used, so a resulting
                # level-up trains that attribute. A failure still grants a sliver
                # (xp_per_failure) — "you learn from failure"; grant_xp no-ops on 0.
                if roll is not None:
                    if roll.outcome == CRITICAL_SUCCESS:
                        amount, reason = self.settings.xp_per_critical, "check"
                    elif roll.outcome == SUCCESS:
                        amount, reason = self.settings.xp_per_success, "check"
                    else:  # FAILURE
                        amount, reason = self.settings.xp_per_failure, "check_failure"
                    level_up = await self.character_sheet.grant_xp(
                        db, session.id, amount, attribute_key=roll.attribute, reason=reason
                    )
                    if level_up is not None:
                        advancement.extend(level_up.notifications())
                # Quest completions: a flat reward (no governing attribute).
                completed = sum(1 for c in quest_changes if c.change == "completed")
                if completed:
                    level_up = await self.character_sheet.grant_xp(
                        db, session.id, self.settings.xp_per_quest_complete * completed, reason="quest"
                    )
                    if level_up is not None:
                        advancement.extend(level_up.notifications())
                # Stakes (todo-rpg Phase 3): a failed *dangerous* check costs HP. The
                # GM tagged severity; the engine owns the number. At 0 HP the character
                # is downed, or the chronicle ends when permadeath is on.
                if roll is not None and roll.outcome == FAILURE:
                    dmg = self.character_sheet.damage_for_stakes(roll.stakes)
                    if dmg > 0:
                        hit = await self.character_sheet.apply_damage(
                            db, session.id, dmg, permadeath=permadeath_on(session, self.settings), reason="check"
                        )
                        if hit is not None:
                            advancement.extend(hit.notifications())
                            if hit.died:
                                session.status = "dead"
            except Exception:
                logger.exception("progression apply failed for session=%s", session.id)

        if advancement:
            try:
                assistant_turn.advancement_json = advancement
                await db.commit()
            except SQLAlchemyError:
                logger.exception("advancement persist failed for session=%s", session.id)
                await db.rollback()
        return advancement

    async def gm_chat(
        self,
        db: AsyncSession,
        session_id: str,
        user_message: str,
        location: str | None = None,
        time_of_day: str | None = None,
    ) -> GMChatResponse:
        """
        GM-driven chat that wraps character interaction with world narration.

        Flow:
        1. Check for events
        2. Generate pre-narration (scene setting based on player action)
        3. Get character response (via normal chat flow)
        4. Generate post-narration (world reaction/consequences)
        5. Potentially inject triggered events
        """
        session = await db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        if session.status == "dead":
            return GMChatResponse(
                session_id=session.id,
                character_reply=_DEAD_CHRONICLE_MSG,
                continuity_applied=False,
                continuity_issues=[],
                retrieved_memories=[],
            )

        # Retrieve memories and recent turns for context
        retrieved = await self.retrieval.retrieve(db, session, user_message)
        recent_turns = (
            await db.scalars(
                select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
            )
        ).all()
        recent_turns = list(reversed(recent_turns))
        recent_events = recent_turns_text(recent_turns[-4:]) if recent_turns else ""

        # Neglected quests pressure the event check toward consequence events
        pressure_quests = []
        if quests_on(session, self.settings):
            try:
                pressure_quests = await self.quests.neglected(db, session)
            except SQLAlchemyError:
                logger.exception("quest pressure check skipped for session=%s", session.id)

        # Check for event trigger
        event_check = await self.game_master.check_for_event(
            db,
            session,
            location=location or "unknown",
            time_of_day=time_of_day or "unknown",
            quest_pressure=QuestService.render_pressure(pressure_quests),
        )

        # Dice / skill check (§4c): roll so the result can steer the character
        # reply. The scene is set before the action resolves, so it does NOT get
        # the roll directive — only the outcome reply (context_packet) does.
        dice_result, roll_directive_text = await self._maybe_roll_skill_check(db, session, user_message)

        # Generate pre-narration (scene setting)
        pre_narration = None
        try:
            pre_narration = await self.game_master.generate_narration(
                world_state=session.world_state,
                recent_events=recent_events,
                player_action=user_message,
                scene_context=location or "",
            )
        except ProviderError:
            logger.exception("Pre-narration failed for session=%s", session.id)

        # Get character response via normal flow
        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self.context.build(session, recent_turns, retrieved, world_state_block, quest_block)

        # Include GM narration in context if available
        if pre_narration:
            context_packet = f"[Scene Narration]\n{pre_narration}\n\n{context_packet}"
        if roll_directive_text:
            context_packet = f"{roll_directive_text}\n\n{context_packet}"

        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=hard_rules_text(session.character_card, session.world_state),
        )

        draft_reply = await self.actor_provider.generate_text(
            [
                ProviderMessage(role="system", content=system_prompt),
                ProviderMessage(role="user", content=f"{context_packet}\n\nCurrent user message:\n{user_message}"),
            ],
            temperature=self.settings.actor_temperature,
            max_tokens=self.settings.actor_reserved_output_tokens,
        )

        # Continuity check
        try:
            continuity = await self.continuity.validate(
                hard_rules=hard_rules_text(session.character_card, session.world_state),
                world_canon=continuity_canon(session, world_state_block),
                recent_transcript=recent_turns_text(recent_turns),
                user_message=user_message,
                draft_reply=draft_reply,
            )
        except ProviderError:
            logger.exception("continuity check skipped for session=%s", session.id)
            continuity = ContinuityResult(final_reply=draft_reply, applied=False, issues=[])

        # Generate event if triggered
        event_response = None
        post_narration = None
        if event_check.should_trigger and event_check.event_seed:
            try:
                generated_event = await self.game_master.generate_event(
                    world_state=session.world_state,
                    event_seed=event_check.event_seed,
                    event_type=event_check.event_type,
                    urgency=event_check.urgency,
                    player_actions=user_message,
                    quest_context=quest_block,
                )
                event_response = GMEventGenerateResponse(
                    event_type=generated_event.event_type,
                    urgency=generated_event.urgency,
                    description=generated_event.description,
                    npcs_involved=generated_event.npcs_involved,
                )
                # Use event description as post-narration
                post_narration = generated_event.description
            except ProviderError:
                logger.exception("Event generation failed for session=%s", session.id)

        # Persist turns (include pre-narration as a GM turn for memory extraction).
        assistant_turn = await self.turns.persist_gm_turns(
            db,
            session,
            user_message=user_message,
            assistant_content=continuity.final_reply,
            pre_narration=pre_narration,
            post_narration=post_narration,
            continuity_notes="\n".join(continuity.issues) if continuity.issues else None,
        )

        if dice_result is not None:
            await self._persist_dice_roll(db, session, dice_result, assistant_turn.id)

        await self.post_turn.refresh_memory(db, session)
        # Plot-hook offers + escalation run first so the post-turn judge sees
        # any freshly-offered quests in its open-quest context (matches the
        # legacy order where the quest judge ran after this).
        quest_changes = await self._post_event_quest_work(
            db,
            session,
            event_check=event_check,
            event_description=post_narration,
            pressure_quests=pressure_quests,
            turn_id=assistant_turn.id,
        )
        extra_changes, suggestions, item_changes = await self.post_turn.judge(
            db,
            session,
            user_message=user_message,
            response_text=assistant_turn.content,
            turn_id=assistant_turn.id,
        )
        quest_changes += extra_changes
        advancement = await self._apply_progression(
            db, session, dice_result, quest_changes, assistant_turn, item_changes
        )

        logger.info(
            "gm_chat session=%s turn_count=%s event_triggered=%s",
            session.id,
            session.turn_count,
            event_check.should_trigger,
        )

        return GMChatResponse(
            session_id=session.id,
            pre_narration=pre_narration,
            character_reply=continuity.final_reply,
            post_narration=post_narration,
            event=event_response,
            roll=dice_result,
            continuity_applied=continuity.applied,
            continuity_issues=continuity.issues,
            quest_updates=self._quest_change_notifications(quest_changes),
            advancement=advancement,
            suggestions=suggestions,
            retrieved_memories=[
                RetrievedMemoryItem(
                    id=item.id,
                    kind=item.kind,
                    content=item.content,
                    weighted_score=item.weighted_score,
                    semantic_score=item.semantic_score,
                    recency_score=item.recency_score,
                    importance=item.importance,
                )
                for item in retrieved
            ],
        )

    async def gm_chat_stream(
        self,
        db: AsyncSession,
        session_id: str,
        user_message: str,
        location: str | None = None,
        time_of_day: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Streaming GM-driven chat with narration and character response.

        Streams each phase as it generates for responsive UI.
        Skips continuity check for speed.
        """
        total_start = time.perf_counter()
        logger.info("gm_chat_stream START session=%s user_message=%s", session_id, user_message[:50])

        session = await db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            logger.warning("gm_chat_stream session=%s NOT FOUND", session_id)
            yield sse_error("Session not found")
            return
        if session.status == "dead":
            yield sse_phase("character_reply")  # makes the frontend mount the reply bubble
            yield sse_chunk(_DEAD_CHRONICLE_MSG)
            yield sse_done(session.id)
            return

        # Retrieve memories and recent turns
        retrieval_start = time.perf_counter()
        with tracer.start_as_current_span("orchestrator.retrieve") as _span:
            _span.set_attribute("rpg.session_id", str(session.id))
            _span.set_attribute("rpg.gm_enabled", True)
            retrieved = await self.retrieval.retrieve(db, session, user_message)
            _span.set_attribute("rpg.retrieved_count", len(retrieved))
            retrieval_selected.record(len(retrieved))
        logger.info(
            "gm_chat_stream session=%s retrieval duration=%.2fs candidates=%d",
            session_id,
            time.perf_counter() - retrieval_start,
            len(retrieved),
        )
        recent_turns = (
            await db.scalars(
                select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
            )
        ).all()
        recent_turns = list(reversed(recent_turns))
        recent_events = recent_turns_text(recent_turns[-4:]) if recent_turns else ""

        # Send retrieved memories
        yield _sse(self._memories_event(retrieved))

        # Neglected quests pressure the event check toward consequence events
        pressure_quests = []
        if quests_on(session, self.settings):
            try:
                pressure_quests = await self.quests.neglected(db, session)
            except SQLAlchemyError:
                logger.exception("quest pressure check skipped for session=%s", session.id)

        # Check for event trigger (fast, no LLM)
        event_start = time.perf_counter()
        with tracer.start_as_current_span("orchestrator.event_check") as _span:
            event_check = await self.game_master.check_for_event(
                db,
                session,
                location=location or "unknown",
                time_of_day=time_of_day or "unknown",
                quest_pressure=QuestService.render_pressure(pressure_quests),
            )
            _span.set_attribute("rpg.event_should_trigger", event_check.should_trigger)
        logger.info(
            "gm_chat_stream session=%s event_check duration=%.2fs should_trigger=%s",
            session_id,
            time.perf_counter() - event_start,
            event_check.should_trigger,
        )

        # Dice / skill check (§4c): compute the roll now so its result can steer
        # the character reply, but emit the frame AFTER the scene narration (see
        # below) so the chip lands in narrative order: scene -> roll -> outcome.
        # The scene is set before the action resolves, so it does NOT get the
        # roll directive — only the outcome reply does.
        dice_result, roll_directive_text = await self._maybe_roll_skill_check(db, session, user_message)

        # Stream pre-narration
        pre_narration_parts: list[str] = []
        pre_narration_failed = False
        pre_narration_start = time.perf_counter()
        try:
            logger.info("gm_chat_stream session=%s pre_narration STARTING", session_id)
            yield sse_phase("pre_narration")
            async for chunk in self.game_master.generate_narration_stream(
                world_state=session.world_state,
                recent_events=recent_events,
                player_action=user_message,
                scene_context=location or "",
            ):
                pre_narration_parts.append(chunk)
                yield sse_pre_narration_chunk(chunk)
        except ProviderError as exc:
            logger.exception("Pre-narration stream failed for session=%s", session.id)
            pre_narration_failed = True
            yield sse_pre_narration_error(str(exc))

        # On failure, discard the partial fragment entirely: a half-written
        # narration must not leak into the actor's context or be persisted.
        pre_narration = "".join(pre_narration_parts) if (pre_narration_parts and not pre_narration_failed) else None
        logger.info(
            "gm_chat_stream session=%s pre_narration DONE duration=%.2fs chars=%d",
            session_id,
            time.perf_counter() - pre_narration_start,
            len(pre_narration or ""),
        )

        # Now that the scene has landed, surface the roll — before the outcome reply.
        if dice_result is not None:
            yield sse_roll(dice_result.model_dump())

        # Build context for character response
        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self.context.build(session, recent_turns, retrieved, world_state_block, quest_block)
        if pre_narration:
            context_packet = f"[Scene Narration]\n{pre_narration}\n\n{context_packet}"
        if roll_directive_text:
            context_packet = f"{roll_directive_text}\n\n{context_packet}"

        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=hard_rules_text(session.character_card, session.world_state),
        )

        # Stream character reply
        character_reply_parts: list[str] = []
        character_start = time.perf_counter()
        try:
            logger.info("gm_chat_stream session=%s character_reply STARTING", session_id)
            yield sse_phase("character_reply")
            async for chunk in self.actor_provider.generate_text_stream(
                [
                    ProviderMessage(role="system", content=system_prompt),
                    ProviderMessage(role="user", content=f"{context_packet}\n\nCurrent user message:\n{user_message}"),
                ],
                temperature=self.settings.actor_temperature,
                max_tokens=self.settings.actor_reserved_output_tokens,
            ):
                character_reply_parts.append(chunk)
                yield sse_chunk(chunk)
        except ProviderError as exc:
            logger.exception("Character reply stream failed for session=%s", session.id)
            yield sse_error(str(exc))
            return

        character_reply = "".join(character_reply_parts)
        logger.info(
            "gm_chat_stream session=%s character_reply DONE duration=%.2fs chars=%d",
            session_id,
            time.perf_counter() - character_start,
            len(character_reply),
        )

        # Generate event if triggered (stream event description as post-narration)
        post_narration = None
        event_response = None
        if event_check.should_trigger and event_check.event_seed:
            event_gen_start = time.perf_counter()
            try:
                logger.info(
                    "gm_chat_stream session=%s event_generation STARTING type=%s", session_id, event_check.event_type
                )
                yield sse_phase("event")
                generated_event = await self.game_master.generate_event(
                    world_state=session.world_state,
                    event_seed=event_check.event_seed,
                    event_type=event_check.event_type,
                    urgency=event_check.urgency,
                    player_actions=user_message,
                    quest_context=quest_block,
                )
                event_response = {
                    "event_type": generated_event.event_type,
                    "urgency": generated_event.urgency,
                    "description": generated_event.description,
                    "npcs_involved": generated_event.npcs_involved,
                }
                post_narration = generated_event.description
                yield sse_event(event_response)
                logger.info(
                    "gm_chat_stream session=%s event_generation DONE duration=%.2fs",
                    session_id,
                    time.perf_counter() - event_gen_start,
                )
            except ProviderError:
                logger.exception("Event generation failed for session=%s", session.id)

        # Rendered before commit: relationships expire on refresh (async lazy-load trap)
        hard_rules = hard_rules_text(session.character_card, session.world_state)
        world_canon = continuity_canon(session, world_state_block)

        # Persist turns (include pre-narration as a GM turn for memory extraction).
        assistant_turn = await self.turns.persist_gm_turns(
            db,
            session,
            user_message=user_message,
            assistant_content=character_reply,
            pre_narration=pre_narration,
            post_narration=post_narration,
        )

        if dice_result is not None:
            await self._persist_dice_roll(db, session, dice_result, assistant_turn.id)

        # Post-stream continuity check → retcon note (reply already shown)
        await self._post_stream_continuity(
            db,
            session,
            user_message=user_message,
            reply_text=character_reply,
            hard_rules=hard_rules,
            world_canon=world_canon,
            recent_transcript=recent_turns_text(recent_turns),
            assistant_turn=assistant_turn,
        )

        # Memory refresh
        yield sse_phase("summarizing")
        await self.post_turn.refresh_memory(db, session)
        # Plot-hook offers + escalation run first so the post-turn judge sees
        # any freshly-offered quests in its open-quest context (matches the
        # legacy order where the quest judge ran after this).
        quest_changes = await self._post_event_quest_work(
            db,
            session,
            event_check=event_check,
            event_description=post_narration,
            pressure_quests=pressure_quests,
            turn_id=assistant_turn.id,
        )
        extra_changes, suggestions, item_changes = await self.post_turn.judge(
            db,
            session,
            user_message=user_message,
            response_text=assistant_turn.content,
            turn_id=assistant_turn.id,
        )
        quest_changes += extra_changes
        advancement = await self._apply_progression(
            db, session, dice_result, quest_changes, assistant_turn, item_changes
        )
        for frame in self._stream_post_turn_results(quest_changes, suggestions, advancement):
            yield frame

        chat_turns.add(1, {"gm_enabled": True})
        total_duration = time.perf_counter() - total_start
        logger.info(
            "gm_chat_stream session=%s COMPLETE turn_count=%s total_duration=%.2fs"
            " pre_narration_chars=%d character_chars=%d",
            session.id,
            session.turn_count,
            total_duration,
            len(pre_narration or ""),
            len(character_reply),
        )

        yield sse_done(session.id)

    async def chat_stream(self, db: AsyncSession, session_id: str, user_message: str) -> AsyncIterator[str]:
        """Stream chat response as Server-Sent Events (SSE)."""
        session = await db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            yield sse_error("Session not found")
            return
        if session.status == "dead":
            # The standard-stream frontend mounts the assistant bubble up front, so
            # a chunk lands directly.
            yield sse_chunk(_DEAD_CHRONICLE_MSG)
            yield sse_done(session.id)
            return

        with tracer.start_as_current_span("orchestrator.retrieve") as _span:
            _span.set_attribute("rpg.session_id", str(session.id))
            retrieved = await self.retrieval.retrieve(db, session, user_message)
            _span.set_attribute("rpg.retrieved_count", len(retrieved))
            retrieval_selected.record(len(retrieved))
        recent_turns = (
            await db.scalars(
                select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
            )
        ).all()
        recent_turns = list(reversed(recent_turns))

        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self.context.build(session, recent_turns, retrieved, world_state_block, quest_block)
        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=hard_rules_text(session.character_card, session.world_state),
        )

        # Send retrieved memories first
        yield _sse(self._memories_event(retrieved))

        # Stream the reply chunks
        full_reply_parts: list[str] = []
        try:
            async for chunk in self.actor_provider.generate_text_stream(
                [
                    ProviderMessage(role="system", content=system_prompt),
                    ProviderMessage(role="user", content=f"{context_packet}\n\nCurrent user message:\n{user_message}"),
                ],
                temperature=self.settings.actor_temperature,
                max_tokens=self.settings.actor_reserved_output_tokens,
            ):
                full_reply_parts.append(chunk)
                yield sse_chunk(chunk)
        except ProviderError as exc:
            logger.exception("chat_stream failed for session=%s", session_id)
            yield sse_error(str(exc))
            return

        full_reply = "".join(full_reply_parts)

        # Rendered before commit: relationships expire on refresh (async lazy-load trap)
        hard_rules = hard_rules_text(session.character_card, session.world_state)
        world_canon = continuity_canon(session, world_state_block)

        # Persist turns to database
        assistant_turn = await self.turns.persist_chat_turns(
            db,
            session,
            user_message=user_message,
            assistant_content=full_reply,
        )

        # Post-stream continuity check → retcon note (reply already shown)
        await self._post_stream_continuity(
            db,
            session,
            user_message=user_message,
            reply_text=full_reply,
            hard_rules=hard_rules,
            world_canon=world_canon,
            recent_transcript=recent_turns_text(recent_turns),
            assistant_turn=assistant_turn,
        )

        # Memory refresh
        yield sse_phase("summarizing")
        await self.post_turn.refresh_memory(db, session)
        quest_changes, suggestions, item_changes = await self.post_turn.judge(
            db,
            session,
            user_message=user_message,
            response_text=full_reply,
            turn_id=assistant_turn.id,
        )
        advancement = await self._apply_progression(db, session, None, quest_changes, assistant_turn, item_changes)
        for frame in self._stream_post_turn_results(quest_changes, suggestions, advancement):
            yield frame

        chat_turns.add(1, {"gm_enabled": False})
        logger.info("chat_stream session=%s turn_count=%s", session.id, session.turn_count)

        # Send completion signal
        yield sse_done(session.id)

    async def _post_stream_continuity(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        reply_text: str,
        hard_rules: str,
        world_canon: str,
        recent_transcript: str,
        assistant_turn: Turn,
    ) -> None:
        """Streaming skips the inline continuity check, so validate after the
        reply is already persisted. The text the user read is never rewritten;
        on contradiction we record a retcon note on the turn, which the next
        context packet injects as a hard constraint so the actor/GM
        self-corrects narratively. Best-effort: never breaks the turn.

        Takes pre-rendered text blocks (not the ORM session relationships):
        it runs after commit/refresh, where touching an expired relationship
        would trigger a sync lazy-load inside the async session."""
        try:
            continuity = await self.continuity.validate(
                hard_rules=hard_rules,
                world_canon=world_canon,
                recent_transcript=recent_transcript,
                user_message=user_message,
                draft_reply=reply_text,
            )
            if continuity.issues:
                assistant_turn.retcon_note = "\n".join(continuity.issues)
                await db.commit()
                continuity_revisions.add(1)
                logger.info(
                    "retcon note recorded for session=%s turn_index=%s issues=%d",
                    session.id,
                    assistant_turn.turn_index,
                    len(continuity.issues),
                )
        except Exception:
            # Deliberately broad: post-turn side effects must never fail the turn.
            logger.exception("post-stream continuity check skipped for session=%s", session.id)

    async def _world_state_block(self, db: AsyncSession, session: ChatSession) -> str:
        """Load + render the canonical world-state ledger for injection.

        Returns "" (no-op) when the feature flag is off or the ledger is empty.
        """
        if not world_state_on(session, self.settings):
            return ""
        with tracer.start_as_current_span("orchestrator.state_inject") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            ledger = await self.world_state.load_current(db, session.id)
            block = self.world_state.render_block(ledger)
            span.set_attribute(
                "rpg.canon.injected_token_estimate",
                0 if not block.strip() else estimate_tokens(block),
            )
            return block

    def _stream_post_turn_results(
        self, quest_changes: list[QuestChange], suggestions: list[str], advancement: list[str] | None = None
    ) -> Iterator[str]:
        """SSE frames for the post-turn results, shared by both stream paths:
        one quest_update per change, then a single suggestions frame (if any),
        then an advancement frame for any level-up beats (if any)."""
        for change in quest_changes:
            yield sse_quest_update(self._quest_change_payload(change))
        if suggestions:
            yield sse_suggestions(suggestions)
        if advancement:
            yield sse_advancement(advancement)

    async def _quest_block(self, db: AsyncSession, session: ChatSession) -> str:
        """Load + render open quests for prompt injection.

        Returns "" (no-op) when the feature flag is off or no quests are open.
        """
        if not quests_on(session, self.settings):
            return ""
        try:
            quests = await self.quests.load_open(db, session.id)
        except SQLAlchemyError:
            logger.exception("quest load skipped for session=%s", session.id)
            return ""
        return self.quests.render_block(quests)

    async def _post_event_quest_work(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        event_check,
        event_description: str | None,
        pressure_quests: list,
        turn_id: str | None,
    ) -> list[QuestChange]:
        """After-commit GM event follow-up: plot hooks become quest offers and
        pressured quests escalate once a consequence event fired. Never breaks
        the turn."""
        if not quests_on(session, self.settings):
            return []
        changes: list[QuestChange] = []
        try:
            if event_description and event_check.event_type == "plot_hook":
                offer = await self.quests.offer_from_event(
                    db,
                    session,
                    event_seed=event_check.event_seed,
                    description=event_description,
                    turn_id=turn_id,
                )
                if offer is not None:
                    changes.append(QuestChange(quest=offer, change="offered", detail=offer.description))
            if pressure_quests:
                consequence_fired = (
                    event_check.should_trigger
                    and event_check.event_type == "consequence"
                    and bool(event_description)  # the event must actually exist in the fiction
                )
                if consequence_fired:
                    changes += await self.quests.mark_escalating(db, session, pressure_quests)
                else:
                    # No consequence this time — stamp the escalation clock so
                    # these quests don't bypass the event probability gate on
                    # every subsequent check.
                    await self.quests.throttle_pressure(db, session, pressure_quests)
        except Exception:
            # Deliberately broad: post-turn side effects must never fail the turn.
            logger.exception("post-event quest work skipped for session=%s", session.id)
        return changes

    @staticmethod
    def _memories_event(retrieved: list) -> dict:
        return {
            "type": "memories",
            "memories": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "content": item.content,
                    "weighted_score": item.weighted_score,
                    "semantic_score": item.semantic_score,
                    "recency_score": item.recency_score,
                    "importance": item.importance,
                }
                for item in retrieved
            ],
        }

    @staticmethod
    def _quest_change_payload(change: QuestChange) -> dict:
        return {
            "quest_id": change.quest.id,
            "slug": change.quest.slug,
            "title": change.quest.title,
            "status": change.quest.status,
            "change": change.change,
            "detail": change.detail,
        }

    @classmethod
    def _quest_change_notifications(cls, changes: list[QuestChange]) -> list[QuestUpdateNotification]:
        return [QuestUpdateNotification(**cls._quest_change_payload(c)) for c in changes]


@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorService:
    try:
        return OrchestratorService()
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc
