from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import EpisodeSummary, MemoryFact, RelationshipState, Turn
from app.models import Session as ChatSession
from app.prompts import EPISODE_SUMMARY_PROMPT, MEMORY_EXTRACT_PROMPT
from app.providers.base import BaseModelProvider, ProviderMessage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryRefreshResult:
    summary_created: bool
    facts_written: int
    relationships_written: int


class MemoryService:
    def __init__(
        self,
        memory_provider: BaseModelProvider,
        embedding_provider: BaseModelProvider,
        settings: Settings | None = None,
    ) -> None:
        self.memory_provider = memory_provider
        self.embedding_provider = embedding_provider
        self.settings = settings or get_settings()

    # Maximum turns to include in a single summary transcript.
    # Prevents overwhelming the LLM when last_summarized_turn falls behind.
    _MAX_TURNS_PER_SUMMARY = 20

    async def maybe_refresh(
        self, db: AsyncSession, session: ChatSession, *, force: bool = False,
    ) -> MemoryRefreshResult:
        turns_since_last = session.turn_count - session.last_summarized_turn
        if not force:
            if session.turn_count == 0 or turns_since_last < self.settings.memory_summary_interval:
                return MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)
        else:
            if session.turn_count == 0 or turns_since_last == 0:
                return MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)

        turns = (await db.scalars(
            select(Turn)
            .where(Turn.session_id == session.id, Turn.turn_index > session.last_summarized_turn)
            .order_by(Turn.turn_index)
        )).all()
        if not turns:
            return MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)

        # Cap the batch so the transcript stays within LLM context limits.
        if len(turns) > self._MAX_TURNS_PER_SUMMARY:
            turns = turns[: self._MAX_TURNS_PER_SUMMARY]

        transcript = self._format_turns(turns)
        summary_payload = await self.memory_provider.generate_json(
            [
                ProviderMessage(role="system", content=EPISODE_SUMMARY_PROMPT),
                ProviderMessage(role="user", content=transcript),
            ],
            temperature=0.2,
            max_tokens=400,
        )
        summary_text = str(summary_payload.get("summary", "")).strip()
        if not summary_text:
            summary_text = "No summary produced."
        summary_importance = self._normalize_importance(summary_payload.get("importance", 0.6))
        summary_embedding = (await self.embedding_provider.embed_texts([summary_text]))[0]

        db.add(
            EpisodeSummary(
                session_id=session.id,
                start_turn_index=turns[0].turn_index,
                end_turn_index=turns[-1].turn_index,
                content=summary_text,
                importance=summary_importance,
                embedding=summary_embedding,
                metadata_json={"turn_span": len(turns)},
            )
        )

        # Always advance the pointer and commit the summary first,
        # so a failure in fact extraction doesn't leave us re-summarizing
        # an ever-growing backlog of turns.
        session.last_summarized_turn = turns[-1].turn_index
        await db.commit()

        facts_written = 0
        relationships_written = 0
        try:
            fact_payload = await self.memory_provider.generate_json(
                [
                    ProviderMessage(role="system", content=MEMORY_EXTRACT_PROMPT),
                    ProviderMessage(role="user", content=transcript),
                ],
                temperature=0.1,
                max_tokens=600,
            )

            for fact in fact_payload.get("facts", []):
                content = str(fact.get("content", "")).strip()
                if not content:
                    continue
                importance = self._normalize_importance(fact.get("importance", 0.5))
                embedding = (await self.embedding_provider.embed_texts([content]))[0]
                db.add(
                    MemoryFact(
                        session_id=session.id,
                        character_card_id=session.character_card_id,
                        source_turn_id=turns[-1].id,
                        content=content,
                        importance=importance,
                        embedding=embedding,
                        metadata_json={"source": "memory_extract"},
                    )
                )
                facts_written += 1

            for relationship in fact_payload.get("relationships", []):
                source_entity = str(relationship.get("source_entity", "")).strip()
                target_entity = str(relationship.get("target_entity", "")).strip()
                status = str(relationship.get("status", "")).strip()
                if not source_entity or not target_entity or not status:
                    continue
                db.add(
                    RelationshipState(
                        session_id=session.id,
                        source_entity=source_entity,
                        target_entity=target_entity,
                        status=status,
                        notes=str(relationship.get("notes", "")).strip() or None,
                        importance=self._normalize_importance(relationship.get("importance", 0.5)),
                        last_observed_turn_id=turns[-1].id,
                    )
                )
                relationships_written += 1

            await db.commit()
        except Exception:
            logger.exception("fact/relationship extraction failed for session=%s, summary still committed", session.id)

        logger.info(
            "memory_refresh session=%s summary_created=%s facts_written=%s relationships_written=%s",
            session.id,
            True,
            facts_written,
            relationships_written,
        )
        return MemoryRefreshResult(summary_created=True, facts_written=facts_written, relationships_written=relationships_written)

    @staticmethod
    def _format_turns(turns: Sequence[Turn]) -> str:
        return "\n".join(f"{turn.role.upper()}: {turn.content}" for turn in turns)

    @staticmethod
    def _normalize_importance(raw_value: object) -> float:
        try:
            value = float(str(raw_value))
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, value))
