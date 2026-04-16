from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import EpisodeSummary, MemoryFact, Session as ChatSession
from app.providers.base import BaseModelProvider


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetrievedMemory:
    id: str
    kind: str
    content: str
    weighted_score: float
    semantic_score: float
    recency_score: float
    importance: float


class RetrievalService:
    def __init__(self, embedding_provider: BaseModelProvider, settings: Settings | None = None) -> None:
        self.embedding_provider = embedding_provider
        self.settings = settings or get_settings()

    async def retrieve(self, db: Session, session: ChatSession, query_text: str) -> list[RetrievedMemory]:
        query_embedding = (await self.embedding_provider.embed_texts([query_text]))[0]
        fact_rows = self._fetch_facts(db, session.id, query_embedding)
        summary_rows = self._fetch_summaries(db, session.id, query_embedding)
        combined = fact_rows + summary_rows
        ranked = sorted(combined, key=lambda item: item.weighted_score, reverse=True)[: self.settings.retrieval_top_k]
        logger.info("retrieval session=%s candidates=%s selected=%s", session.id, len(combined), len(ranked))
        return ranked

    def _fetch_facts(self, db: Session, session_id: str, query_embedding: list[float]) -> list[RetrievedMemory]:
        distance = MemoryFact.embedding.cosine_distance(query_embedding).label("distance")
        stmt: Select = (
            select(MemoryFact, distance)
            .where(MemoryFact.session_id == session_id)
            .order_by(distance)
            .limit(self.settings.retrieval_candidate_pool)
        )
        return [
            self._to_result(record.id, "fact", record.content, score, record.importance, record.created_at)
            for record, score in db.execute(stmt).all()
        ]

    def _fetch_summaries(self, db: Session, session_id: str, query_embedding: list[float]) -> list[RetrievedMemory]:
        distance = EpisodeSummary.embedding.cosine_distance(query_embedding).label("distance")
        stmt: Select = (
            select(EpisodeSummary, distance)
            .where(EpisodeSummary.session_id == session_id)
            .order_by(distance)
            .limit(self.settings.retrieval_candidate_pool)
        )
        return [
            self._to_result(record.id, "summary", record.content, score, record.importance, record.created_at)
            for record, score in db.execute(stmt).all()
        ]

    def _to_result(
        self,
        item_id: str,
        kind: str,
        content: str,
        distance: float,
        importance: float,
        created_at: datetime,
    ) -> RetrievedMemory:
        semantic_score = max(0.0, 1.0 - float(distance))
        recency_score = self._recency_score(created_at)
        importance_score = self._clamp(importance)
        weighted_score = (0.6 * semantic_score) + (0.25 * recency_score) + (0.15 * importance_score)
        return RetrievedMemory(
            id=item_id,
            kind=kind,
            content=content,
            weighted_score=round(weighted_score, 4),
            semantic_score=round(semantic_score, 4),
            recency_score=round(recency_score, 4),
            importance=round(importance_score, 4),
        )

    def _recency_score(self, created_at: datetime) -> float:
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - created_at).total_seconds() / 3600)
        return math.exp(-age_hours / max(1, self.settings.recency_half_life_hours))

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
