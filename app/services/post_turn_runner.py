"""Best-effort post-turn work shared by the orchestrator's entry points.

After a turn is persisted, every path runs the same best-effort tail: refresh
long-term memory, then the unified judge (world-state delta + quest delta +
suggestion chips). Both are wrapped so a failure is logged and swallowed —
post-turn side effects must never break the turn (repo convention).

These stay two separate calls rather than one bundled step because the GM paths
insert their event-driven quest work *between* them: the plot-hook offers must
land before the judge runs so the judge sees freshly-offered quests in its
open-quest context.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as ChatSession
from app.providers.base import ProviderError
from app.services.items import ItemChange
from app.services.memory import MemoryService
from app.services.post_turn_judge import PostTurnJudgeService
from app.services.quests import QuestChange
from app.telemetry import tracer

logger = logging.getLogger(__name__)


class PostTurnRunner:
    def __init__(self, memory: MemoryService, post_turn_judge: PostTurnJudgeService) -> None:
        self.memory = memory
        self.post_turn_judge = post_turn_judge

    async def refresh_memory(self, db: AsyncSession, session: ChatSession) -> None:
        """Best-effort long-term memory refresh (facts + periodic summary)."""
        try:
            with tracer.start_as_current_span("orchestrator.memory_refresh"):
                await self.memory.maybe_refresh(db, session)
        except ProviderError:
            logger.exception("memory refresh skipped for session=%s", session.id)

    async def judge(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        response_text: str,
        turn_id: str | None,
    ) -> tuple[list[QuestChange], list[str], list[ItemChange]]:
        """Run the unified post-turn judge and return ``(quest_changes,
        suggestions, item_changes)``. Best-effort: never raises — a post-turn
        failure must not break the turn."""
        try:
            _, quest_changes, suggestions, item_changes = await self.post_turn_judge.judge_turn(
                db,
                session,
                user_message=user_message,
                response_text=response_text,
                turn_id=turn_id,
            )
            return quest_changes, suggestions, item_changes
        except Exception:
            # Deliberately broad: post-turn side effects must never fail the turn.
            logger.exception("post-turn judge skipped for session=%s", session.id)
            return [], [], []
