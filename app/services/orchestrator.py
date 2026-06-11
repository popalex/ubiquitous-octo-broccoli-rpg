from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings, get_settings
from app.models import CharacterCard, Turn, WorldState
from app.models import Session as ChatSession
from app.prompts import ACTOR_SYSTEM_PROMPT
from app.providers.base import ProviderError, ProviderMessage, build_provider
from app.schemas import (
    ChatResponse,
    GMChatResponse,
    GMEventGenerateResponse,
    QuestUpdateNotification,
    RetrievedMemoryItem,
)
from app.services.continuity import ContinuityResult, ContinuityService
from app.services.game_master import GameMasterService
from app.services.memory import MemoryService
from app.services.quests import QuestChange, QuestService
from app.services.retrieval import RetrievalService
from app.services.world_state import WorldStateService
from app.telemetry import chat_turns, retrieval_selected, tracer

logger = logging.getLogger(__name__)


class OrchestratorService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.actor_provider = build_provider(self.settings.actor_provider, self.settings.actor_model_name, self.settings)
        self.memory_provider = build_provider(self.settings.memory_provider, self.settings.memory_model_name, self.settings)
        self.embedding_provider = build_provider(self.settings.embedding_provider, self.settings.embedding_model_name, self.settings)
        self.gm_provider = build_provider(self.settings.gm_provider, self.settings.gm_model_name, self.settings)
        self.retrieval = RetrievalService(self.embedding_provider, self.settings)
        self.memory = MemoryService(self.memory_provider, self.embedding_provider, self.settings)
        self.continuity = ContinuityService(self.memory_provider)
        self.game_master = GameMasterService(self.gm_provider, self.settings)
        self.world_state = WorldStateService(self.memory_provider, self.settings)
        self.quests = QuestService(self.memory_provider, self.settings)

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

        retrieved = await self.retrieval.retrieve(db, session, user_message)
        recent_turns = (await db.scalars(
            select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
        )).all()
        recent_turns = list(reversed(recent_turns))

        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self._build_context_packet(session, recent_turns, retrieved, world_state_block, quest_block)
        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=self._hard_rules_text(session.character_card, session.world_state),
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
                hard_rules=self._hard_rules_text(session.character_card, session.world_state),
                world_canon=self._continuity_canon(session, world_state_block),
                recent_transcript=self._recent_turns_text(recent_turns),
                user_message=user_message,
                draft_reply=draft_reply,
            )
        except ProviderError:
            logger.exception("continuity check skipped for session=%s", session.id)
            continuity = ContinuityResult(final_reply=draft_reply, applied=False, issues=[])

        next_user_index = session.turn_count + 1
        next_actor_index = session.turn_count + 2
        assistant_turn = Turn(
            session_id=session.id,
            turn_index=next_actor_index,
            role="assistant",
            content=continuity.final_reply,
            token_estimate=self._estimate_tokens(continuity.final_reply),
            continuity_notes="\n".join(continuity.issues) if continuity.issues else None,
        )
        db.add_all(
            [
                Turn(
                    session_id=session.id,
                    turn_index=next_user_index,
                    role="user",
                    content=user_message,
                    token_estimate=self._estimate_tokens(user_message),
                ),
                assistant_turn,
            ]
        )
        session.turn_count = next_actor_index
        await db.commit()
        await db.refresh(session)

        try:
            await self.memory.maybe_refresh(db, session)
        except ProviderError:
            logger.exception("memory refresh skipped for session=%s", session.id)
        await self._extract_world_state(
            db, session, user_message=user_message, gm_response=continuity.final_reply, turn_id=assistant_turn.id,
        )
        quest_changes = await self._extract_quests(
            db, session, user_message=user_message, response_text=continuity.final_reply, turn_id=assistant_turn.id,
        )
        logger.info("chat session=%s turn_count=%s continuity_applied=%s", session.id, session.turn_count, continuity.applied)

        return ChatResponse(
            session_id=session.id,
            reply=continuity.final_reply,
            continuity_applied=continuity.applied,
            continuity_issues=continuity.issues,
            quest_updates=self._quest_change_notifications(quest_changes),
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

        # Retrieve memories and recent turns for context
        retrieved = await self.retrieval.retrieve(db, session, user_message)
        recent_turns = (await db.scalars(
            select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
        )).all()
        recent_turns = list(reversed(recent_turns))
        recent_events = self._recent_turns_text(recent_turns[-4:]) if recent_turns else ""

        # Neglected quests pressure the event check toward consequence events
        pressure_quests = []
        if self.settings.quests_enabled:
            try:
                pressure_quests = await self.quests.neglected(db, session)
            except Exception:
                logger.exception("quest pressure check skipped for session=%s", session.id)

        # Check for event trigger
        event_check = await self.game_master.check_for_event(
            db,
            session,
            location=location or "unknown",
            time_of_day=time_of_day or "unknown",
            quest_pressure=QuestService.render_pressure(pressure_quests),
        )

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
        context_packet = self._build_context_packet(session, recent_turns, retrieved, world_state_block, quest_block)

        # Include GM narration in context if available
        if pre_narration:
            context_packet = f"[Scene Narration]\n{pre_narration}\n\n{context_packet}"

        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=self._hard_rules_text(session.character_card, session.world_state),
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
                hard_rules=self._hard_rules_text(session.character_card, session.world_state),
                world_canon=self._continuity_canon(session, world_state_block),
                recent_transcript=self._recent_turns_text(recent_turns),
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

        # Persist turns (include pre-narration as GM turn for memory extraction)
        turns_to_add: list[Turn] = []
        current_index = session.turn_count

        # Store pre-narration as a separate GM turn if present
        if pre_narration:
            current_index += 1
            turns_to_add.append(
                Turn(
                    session_id=session.id,
                    turn_index=current_index,
                    role="assistant",
                    content=f"[Scene Narration]\n{pre_narration}",
                    token_estimate=self._estimate_tokens(pre_narration),
                    turn_type="gm_narration",
                )
            )

        # User turn
        current_index += 1
        turns_to_add.append(
            Turn(
                session_id=session.id,
                turn_index=current_index,
                role="user",
                content=user_message,
                token_estimate=self._estimate_tokens(user_message),
            )
        )

        # Build full assistant content including post-narration
        full_assistant_content = continuity.final_reply
        if post_narration:
            full_assistant_content = f"{continuity.final_reply}\n\n---\n\n{post_narration}"

        # Assistant turn
        current_index += 1
        turns_to_add.append(
            Turn(
                session_id=session.id,
                turn_index=current_index,
                role="assistant",
                content=full_assistant_content,
                token_estimate=self._estimate_tokens(full_assistant_content),
                continuity_notes="\n".join(continuity.issues) if continuity.issues else None,
            )
        )

        db.add_all(turns_to_add)
        session.turn_count = current_index
        await db.commit()
        await db.refresh(session)

        # Memory refresh
        try:
            await self.memory.maybe_refresh(db, session)
        except ProviderError:
            logger.exception("memory refresh skipped for session=%s", session.id)
        await self._extract_world_state(
            db, session, user_message=user_message, gm_response=full_assistant_content,
            turn_id=turns_to_add[-1].id,
        )
        quest_changes = await self._post_event_quest_work(
            db,
            session,
            event_check=event_check,
            event_description=post_narration,
            pressure_quests=pressure_quests,
            turn_id=turns_to_add[-1].id,
        )
        quest_changes += await self._extract_quests(
            db, session, user_message=user_message, response_text=full_assistant_content,
            turn_id=turns_to_add[-1].id,
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
            continuity_applied=continuity.applied,
            continuity_issues=continuity.issues,
            quest_updates=self._quest_change_notifications(quest_changes),
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
            yield f"data: {json.dumps({'type': 'error', 'error': 'Session not found'})}\n\n"
            return

        # Retrieve memories and recent turns
        retrieval_start = time.perf_counter()
        with tracer.start_as_current_span("orchestrator.retrieve") as _span:
            _span.set_attribute("rpg.session_id", str(session.id))
            _span.set_attribute("rpg.gm_enabled", True)
            retrieved = await self.retrieval.retrieve(db, session, user_message)
            _span.set_attribute("rpg.retrieved_count", len(retrieved))
            retrieval_selected.record(len(retrieved))
        logger.info("gm_chat_stream session=%s retrieval duration=%.2fs candidates=%d", session_id, time.perf_counter() - retrieval_start, len(retrieved))
        recent_turns = (await db.scalars(
            select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
        )).all()
        recent_turns = list(reversed(recent_turns))
        recent_events = self._recent_turns_text(recent_turns[-4:]) if recent_turns else ""

        # Send retrieved memories
        yield f"data: {json.dumps({'type': 'memories', 'memories': [{'id': item.id, 'kind': item.kind, 'content': item.content, 'weighted_score': item.weighted_score, 'semantic_score': item.semantic_score, 'recency_score': item.recency_score, 'importance': item.importance} for item in retrieved]})}\n\n"

        # Neglected quests pressure the event check toward consequence events
        pressure_quests = []
        if self.settings.quests_enabled:
            try:
                pressure_quests = await self.quests.neglected(db, session)
            except Exception:
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
        logger.info("gm_chat_stream session=%s event_check duration=%.2fs should_trigger=%s", session_id, time.perf_counter() - event_start, event_check.should_trigger)

        # Stream pre-narration
        pre_narration_parts: list[str] = []
        pre_narration_start = time.perf_counter()
        try:
            logger.info("gm_chat_stream session=%s pre_narration STARTING", session_id)
            yield f"data: {json.dumps({'type': 'phase', 'phase': 'pre_narration'})}\n\n"
            async for chunk in self.game_master.generate_narration_stream(
                world_state=session.world_state,
                recent_events=recent_events,
                player_action=user_message,
                scene_context=location or "",
            ):
                pre_narration_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'pre_narration_chunk', 'content': chunk})}\n\n"
        except ProviderError as exc:
            logger.exception("Pre-narration stream failed for session=%s", session.id)
            yield f"data: {json.dumps({'type': 'pre_narration_error', 'error': str(exc)})}\n\n"

        pre_narration = "".join(pre_narration_parts) if pre_narration_parts else None
        logger.info("gm_chat_stream session=%s pre_narration DONE duration=%.2fs chars=%d", session_id, time.perf_counter() - pre_narration_start, len(pre_narration or ""))

        # Build context for character response
        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self._build_context_packet(session, recent_turns, retrieved, world_state_block, quest_block)
        if pre_narration:
            context_packet = f"[Scene Narration]\n{pre_narration}\n\n{context_packet}"

        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=self._hard_rules_text(session.character_card, session.world_state),
        )

        # Stream character reply
        character_reply_parts: list[str] = []
        character_start = time.perf_counter()
        try:
            logger.info("gm_chat_stream session=%s character_reply STARTING", session_id)
            yield f"data: {json.dumps({'type': 'phase', 'phase': 'character_reply'})}\n\n"
            async for chunk in self.actor_provider.generate_text_stream(
                [
                    ProviderMessage(role="system", content=system_prompt),
                    ProviderMessage(role="user", content=f"{context_packet}\n\nCurrent user message:\n{user_message}"),
                ],
                temperature=self.settings.actor_temperature,
                max_tokens=self.settings.actor_reserved_output_tokens,
            ):
                character_reply_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except ProviderError as exc:
            logger.exception("Character reply stream failed for session=%s", session.id)
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            return

        character_reply = "".join(character_reply_parts)
        logger.info("gm_chat_stream session=%s character_reply DONE duration=%.2fs chars=%d", session_id, time.perf_counter() - character_start, len(character_reply))

        # Generate event if triggered (stream event description as post-narration)
        post_narration = None
        event_response = None
        if event_check.should_trigger and event_check.event_seed:
            event_gen_start = time.perf_counter()
            try:
                logger.info("gm_chat_stream session=%s event_generation STARTING type=%s", session_id, event_check.event_type)
                yield f"data: {json.dumps({'type': 'phase', 'phase': 'event'})}\n\n"
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
                yield f"data: {json.dumps({'type': 'event', 'event': event_response})}\n\n"
                logger.info("gm_chat_stream session=%s event_generation DONE duration=%.2fs", session_id, time.perf_counter() - event_gen_start)
            except ProviderError:
                logger.exception("Event generation failed for session=%s", session.id)

        # Persist turns (include pre-narration as GM turn for memory extraction)
        turns_to_add: list[Turn] = []
        current_index = session.turn_count

        # Store pre-narration as a separate GM turn if present
        if pre_narration:
            current_index += 1
            turns_to_add.append(
                Turn(
                    session_id=session.id,
                    turn_index=current_index,
                    role="assistant",
                    content=f"[Scene Narration]\n{pre_narration}",
                    token_estimate=self._estimate_tokens(pre_narration),
                    turn_type="gm_narration",
                )
            )

        # User turn
        current_index += 1
        turns_to_add.append(
            Turn(
                session_id=session.id,
                turn_index=current_index,
                role="user",
                content=user_message,
                token_estimate=self._estimate_tokens(user_message),
            )
        )

        # Build full assistant content including post-narration
        full_assistant_content = character_reply
        if post_narration:
            full_assistant_content = f"{character_reply}\n\n---\n\n{post_narration}"

        # Assistant turn
        current_index += 1
        turns_to_add.append(
            Turn(
                session_id=session.id,
                turn_index=current_index,
                role="assistant",
                content=full_assistant_content,
                token_estimate=self._estimate_tokens(full_assistant_content),
            )
        )

        db.add_all(turns_to_add)
        session.turn_count = current_index
        await db.commit()
        await db.refresh(session)

        # Memory refresh
        yield f"data: {json.dumps({'type': 'phase', 'phase': 'summarizing'})}\n\n"
        try:
            with tracer.start_as_current_span("orchestrator.memory_refresh"):
                await self.memory.maybe_refresh(db, session)
        except ProviderError:
            logger.exception("memory refresh skipped for session=%s", session.id)
        await self._extract_world_state(
            db, session, user_message=user_message, gm_response=full_assistant_content,
            turn_id=turns_to_add[-1].id,
        )
        quest_changes = await self._post_event_quest_work(
            db,
            session,
            event_check=event_check,
            event_description=post_narration,
            pressure_quests=pressure_quests,
            turn_id=turns_to_add[-1].id,
        )
        quest_changes += await self._extract_quests(
            db, session, user_message=user_message, response_text=full_assistant_content,
            turn_id=turns_to_add[-1].id,
        )
        for change in quest_changes:
            yield f"data: {json.dumps({'type': 'quest_update', 'quest': self._quest_change_payload(change)})}\n\n"

        chat_turns.add(1, {"gm_enabled": True})
        total_duration = time.perf_counter() - total_start
        logger.info("gm_chat_stream session=%s COMPLETE turn_count=%s total_duration=%.2fs pre_narration_chars=%d character_chars=%d",
                    session.id, session.turn_count, total_duration, len(pre_narration or ""), len(character_reply))

        yield f"data: {json.dumps({'type': 'done', 'session_id': session.id})}\n\n"

    async def chat_stream(self, db: AsyncSession, session_id: str, user_message: str) -> AsyncIterator[str]:
        """Stream chat response as Server-Sent Events (SSE)."""
        session = await db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        with tracer.start_as_current_span("orchestrator.retrieve") as _span:
            _span.set_attribute("rpg.session_id", str(session.id))
            retrieved = await self.retrieval.retrieve(db, session, user_message)
            _span.set_attribute("rpg.retrieved_count", len(retrieved))
            retrieval_selected.record(len(retrieved))
        recent_turns = (await db.scalars(
            select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
        )).all()
        recent_turns = list(reversed(recent_turns))

        world_state_block = await self._world_state_block(db, session)
        quest_block = await self._quest_block(db, session)
        context_packet = self._build_context_packet(session, recent_turns, retrieved, world_state_block, quest_block)
        system_prompt = ACTOR_SYSTEM_PROMPT.format(
            character_name=session.character_card.name,
            character_description=session.character_card.description,
            style_guide=session.character_card.style_guide or "Stay grounded, sensory, and concise.",
            hard_rules=self._hard_rules_text(session.character_card, session.world_state),
        )

        # Send retrieved memories first
        yield f"data: {json.dumps({'type': 'memories', 'memories': [{'id': item.id, 'kind': item.kind, 'content': item.content, 'weighted_score': item.weighted_score, 'semantic_score': item.semantic_score, 'recency_score': item.recency_score, 'importance': item.importance} for item in retrieved]})}\n\n"

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
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except ProviderError as exc:
            logger.exception("chat_stream failed for session=%s", session_id)
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            return

        full_reply = "".join(full_reply_parts)

        # Persist turns to database
        next_user_index = session.turn_count + 1
        next_actor_index = session.turn_count + 2
        assistant_turn = Turn(
            session_id=session.id,
            turn_index=next_actor_index,
            role="assistant",
            content=full_reply,
            token_estimate=self._estimate_tokens(full_reply),
        )
        db.add_all(
            [
                Turn(
                    session_id=session.id,
                    turn_index=next_user_index,
                    role="user",
                    content=user_message,
                    token_estimate=self._estimate_tokens(user_message),
                ),
                assistant_turn,
            ]
        )
        session.turn_count = next_actor_index
        await db.commit()
        await db.refresh(session)

        # Memory refresh
        yield f"data: {json.dumps({'type': 'phase', 'phase': 'summarizing'})}\n\n"
        try:
            with tracer.start_as_current_span("orchestrator.memory_refresh"):
                await self.memory.maybe_refresh(db, session)
        except ProviderError:
            logger.exception("memory refresh skipped for session=%s", session.id)
        await self._extract_world_state(
            db, session, user_message=user_message, gm_response=full_reply, turn_id=assistant_turn.id,
        )
        quest_changes = await self._extract_quests(
            db, session, user_message=user_message, response_text=full_reply, turn_id=assistant_turn.id,
        )
        for change in quest_changes:
            yield f"data: {json.dumps({'type': 'quest_update', 'quest': self._quest_change_payload(change)})}\n\n"

        chat_turns.add(1, {"gm_enabled": False})
        logger.info("chat_stream session=%s turn_count=%s", session.id, session.turn_count)

        # Send completion signal
        yield f"data: {json.dumps({'type': 'done', 'session_id': session.id})}\n\n"

    async def _world_state_block(self, db: AsyncSession, session: ChatSession) -> str:
        """Load + render the canonical world-state ledger for injection.

        Returns "" (no-op) when the feature flag is off or the ledger is empty.
        """
        if not self.settings.world_state_enabled:
            return ""
        with tracer.start_as_current_span("orchestrator.state_inject") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            ledger = await self.world_state.load_current(db, session.id)
            block = self.world_state.render_block(ledger)
            span.set_attribute(
                "rpg.canon.injected_token_estimate",
                0 if not block.strip() else self._estimate_tokens(block),
            )
            return block

    async def _extract_world_state(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        gm_response: str,
        turn_id: str | None = None,
    ) -> None:
        """Fire the after-turn world-state extraction; never break the turn."""
        if not self.settings.world_state_enabled:
            return
        try:
            await self.world_state.extract_and_apply(
                db,
                session,
                user_message=user_message,
                gm_response=gm_response,
                turn_id=turn_id,
            )
        except Exception:
            logger.exception("world-state extract skipped for session=%s", session.id)

    async def _quest_block(self, db: AsyncSession, session: ChatSession) -> str:
        """Load + render open quests for prompt injection.

        Returns "" (no-op) when the feature flag is off or no quests are open.
        """
        if not self.settings.quests_enabled:
            return ""
        try:
            quests = await self.quests.load_open(db, session.id)
        except Exception:
            logger.exception("quest load skipped for session=%s", session.id)
            return ""
        return self.quests.render_block(quests)

    async def _extract_quests(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        response_text: str,
        turn_id: str | None = None,
    ) -> list[QuestChange]:
        """Fire the after-turn quest judge; never break the turn."""
        if not self.settings.quests_enabled:
            return []
        try:
            return await self.quests.extract_and_apply(
                db,
                session,
                user_message=user_message,
                response_text=response_text,
                turn_id=turn_id,
            )
        except Exception:
            logger.exception("quest extract skipped for session=%s", session.id)
            return []

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
        if not self.settings.quests_enabled:
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
            if pressure_quests and event_check.should_trigger:
                changes += await self.quests.mark_escalating(db, session, pressure_quests)
        except Exception:
            logger.exception("post-event quest work skipped for session=%s", session.id)
        return changes

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

    def _build_context_packet(
        self,
        session: ChatSession,
        recent_turns: list[Turn],
        retrieved: list,
        world_state_block: str = "",
        quest_block: str = "",
    ) -> str:
        remaining_budget = self.settings.actor_context_budget
        sections: list[str] = []

        if world_state_block.strip():
            remaining_budget = self._append_section(
                sections, "Canonical World State", world_state_block, remaining_budget, required=True
            )

        if quest_block.strip():
            remaining_budget = self._append_section(
                sections, "Active Quests", quest_block, remaining_budget
            )

        hard_rules = self._hard_rules_text(session.character_card, session.world_state)
        remaining_budget = self._append_section(sections, "Hard Rules And Canon", hard_rules, remaining_budget, required=True)

        recent_text = self._recent_turns_text(recent_turns)
        remaining_budget = self._append_section(sections, "Recent Turns", recent_text, remaining_budget)

        facts = "\n".join(f"- {item.content}" for item in retrieved if item.kind == "fact")
        remaining_budget = self._append_section(sections, "Retrieved Facts", facts, remaining_budget)

        summaries = "\n".join(f"- {item.content}" for item in retrieved if item.kind == "summary")
        self._append_section(sections, "Episode Summaries", summaries, remaining_budget)

        return "\n\n".join(section for section in sections if section.strip())

    def _append_section(self, sections: list[str], title: str, body: str, remaining_budget: int, *, required: bool = False) -> int:
        if not body.strip():
            return remaining_budget
        cost = self._estimate_tokens(body)
        if cost > remaining_budget and not required:
            return remaining_budget
        sections.append(f"{title}:\n{body}")
        return max(0, remaining_budget - cost)

    @staticmethod
    def _recent_turns_text(turns: list[Turn]) -> str:
        return "\n".join(f"{turn.role.upper()}: {turn.content}" for turn in turns)

    @staticmethod
    def _continuity_canon(session: ChatSession, world_state_block: str) -> str:
        """Canon text continuity defends: the static world canon plus, when
        enabled, the live ledger (the authoritative source of truth)."""
        canon = session.world_state.canon if session.world_state else ""
        if world_state_block.strip():
            return f"{world_state_block}\n\n{canon}".strip()
        return canon

    @staticmethod
    def _hard_rules_text(character: CharacterCard, world: WorldState | None) -> str:
        parts = [character.hard_rules]
        if world is not None:
            if world.hard_rules.strip():
                parts.append(world.hard_rules)
            if world.canon.strip():
                parts.append(f"Canon:\n{world.canon}")
        return "\n\n".join(part for part in parts if part.strip())

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))


@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorService:
    try:
        return OrchestratorService()
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc
