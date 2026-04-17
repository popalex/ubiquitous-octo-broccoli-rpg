from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.models import CharacterCard, Session as ChatSession, Turn, WorldState
from app.prompts import ACTOR_SYSTEM_PROMPT
from app.providers.base import ProviderError, ProviderMessage, build_provider
from app.schemas import ChatResponse, RetrievedMemoryItem
from app.services.continuity import ContinuityService
from app.services.memory import MemoryService
from app.services.continuity import ContinuityResult
from app.services.retrieval import RetrievalService


logger = logging.getLogger(__name__)


class OrchestratorService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.actor_provider = build_provider(self.settings.actor_provider, self.settings.actor_model_name, self.settings)
        self.memory_provider = build_provider(self.settings.memory_provider, self.settings.memory_model_name, self.settings)
        self.embedding_provider = build_provider(self.settings.embedding_provider, self.settings.embedding_model_name, self.settings)
        self.retrieval = RetrievalService(self.embedding_provider, self.settings)
        self.memory = MemoryService(self.memory_provider, self.embedding_provider, self.settings)
        self.continuity = ContinuityService(self.memory_provider)

    async def chat(self, db: Session, session_id: str, user_message: str) -> ChatResponse:
        session = db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")

        retrieved = await self.retrieval.retrieve(db, session, user_message)
        recent_turns = db.scalars(
            select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
        ).all()
        recent_turns = list(reversed(recent_turns))

        context_packet = self._build_context_packet(session, recent_turns, retrieved)
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
                world_canon=session.world_state.canon if session.world_state else "",
                recent_transcript=self._recent_turns_text(recent_turns),
                user_message=user_message,
                draft_reply=draft_reply,
            )
        except ProviderError as exc:
            logger.warning("continuity check skipped for session=%s: %s", session.id, exc)
            continuity = ContinuityResult(final_reply=draft_reply, applied=False, issues=[])

        next_user_index = session.turn_count + 1
        next_actor_index = session.turn_count + 2
        db.add_all(
            [
                Turn(
                    session_id=session.id,
                    turn_index=next_user_index,
                    role="user",
                    content=user_message,
                    token_estimate=self._estimate_tokens(user_message),
                ),
                Turn(
                    session_id=session.id,
                    turn_index=next_actor_index,
                    role="assistant",
                    content=continuity.final_reply,
                    token_estimate=self._estimate_tokens(continuity.final_reply),
                    continuity_notes="\n".join(continuity.issues) if continuity.issues else None,
                ),
            ]
        )
        session.turn_count = next_actor_index
        db.commit()
        db.refresh(session)

        try:
            await self.memory.maybe_refresh(db, session)
        except ProviderError as exc:
            logger.warning("memory refresh skipped for session=%s: %s", session.id, exc)
        logger.info("chat session=%s turn_count=%s continuity_applied=%s", session.id, session.turn_count, continuity.applied)

        return ChatResponse(
            session_id=session.id,
            reply=continuity.final_reply,
            continuity_applied=continuity.applied,
            continuity_issues=continuity.issues,
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

    async def chat_stream(self, db: Session, session_id: str, user_message: str) -> AsyncIterator[str]:
        """Stream chat response as Server-Sent Events (SSE)."""
        session = db.scalar(
            select(ChatSession)
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .where(ChatSession.id == session_id)
        )
        if session is None:
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        retrieved = await self.retrieval.retrieve(db, session, user_message)
        recent_turns = db.scalars(
            select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(8)
        ).all()
        recent_turns = list(reversed(recent_turns))

        context_packet = self._build_context_packet(session, recent_turns, retrieved)
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
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            return

        full_reply = "".join(full_reply_parts)

        # Persist turns to database
        next_user_index = session.turn_count + 1
        next_actor_index = session.turn_count + 2
        db.add_all(
            [
                Turn(
                    session_id=session.id,
                    turn_index=next_user_index,
                    role="user",
                    content=user_message,
                    token_estimate=self._estimate_tokens(user_message),
                ),
                Turn(
                    session_id=session.id,
                    turn_index=next_actor_index,
                    role="assistant",
                    content=full_reply,
                    token_estimate=self._estimate_tokens(full_reply),
                ),
            ]
        )
        session.turn_count = next_actor_index
        db.commit()
        db.refresh(session)

        # Trigger memory refresh in background (non-blocking)
        try:
            await self.memory.maybe_refresh(db, session)
        except ProviderError as exc:
            logger.warning("memory refresh skipped for session=%s: %s", session.id, exc)

        logger.info("chat_stream session=%s turn_count=%s", session.id, session.turn_count)

        # Send completion signal
        yield f"data: {json.dumps({'type': 'done', 'session_id': session.id})}\n\n"

    def _build_context_packet(self, session: ChatSession, recent_turns: list[Turn], retrieved: list) -> str:
        remaining_budget = self.settings.actor_context_budget
        sections: list[str] = []

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
