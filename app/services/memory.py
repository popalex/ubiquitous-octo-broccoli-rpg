from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import EpisodeSummary, MemoryFact, RelationshipState, Session as ChatSession, Turn
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

    async def maybe_refresh(self, db: Session, session: ChatSession) -> MemoryRefreshResult:
        if session.turn_count == 0 or session.turn_count % self.settings.memory_summary_interval != 0:
            return MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)

        turns = db.scalars(
            select(Turn)
            .where(Turn.session_id == session.id, Turn.turn_index > session.last_summarized_turn)
            .order_by(Turn.turn_index)
        ).all()
        if not turns:
            return MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)

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

        fact_payload = await self.memory_provider.generate_json(
            [
                ProviderMessage(role="system", content=MEMORY_EXTRACT_PROMPT),
                ProviderMessage(role="user", content=transcript),
            ],
            temperature=0.1,
            max_tokens=600,
        )

        facts_written = 0
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

        relationships_written = 0
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

        session.last_summarized_turn = turns[-1].turn_index
        db.commit()
        logger.info(
            "memory_refresh session=%s summary_created=%s facts_written=%s relationships_written=%s",
            session.id,
            True,
            facts_written,
            relationships_written,
        )
        return MemoryRefreshResult(summary_created=True, facts_written=facts_written, relationships_written=relationships_written)

    @staticmethod
    def _format_turns(turns: list[Turn]) -> str:
        return "\n".join(f"{turn.role.upper()}: {turn.content}" for turn in turns)

    @staticmethod
    def _normalize_importance(raw_value: object) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, value))
