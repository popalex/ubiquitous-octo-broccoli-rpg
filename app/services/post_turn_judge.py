"""Unified post-turn judge (§2).

Folds the two per-turn extraction calls — world-state ledger and quest judge —
into a SINGLE ``generate_json`` call when at least one feature is enabled,
instead of one call each. Memory (facts + episode summary) keeps its own
6-turn cadence and is untouched.

The combined prompt reuses the exact world-state and quest guidance/schema
fragments (see ``app.prompts.build_post_turn_judge_prompt``), and each section
of the response is parsed and applied **independently** through the existing
service apply paths, so a malformed or failing section never sinks the other —
and the whole thing is best-effort, never breaking the turn.

Ships dark behind ``post_turn_judge_enabled``; the orchestrator keeps the
legacy two-call path as the fallback.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models import Quest, WorldStateLedger
from app.models import Session as ChatSession
from app.prompts import build_post_turn_judge_prompt
from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage
from app.services.features import quests_on, world_state_on
from app.services.quests import QuestChange, QuestDelta, QuestService
from app.services.world_state import LedgerDelta, WorldStateService
from app.telemetry import (
    canon_extract_failures,
    post_turn_judge_calls,
    post_turn_suggestions,
    record_span_error,
    set_completion,
    tracer,
)

logger = logging.getLogger(__name__)


class PostTurnJudgeService:
    def __init__(
        self,
        provider: BaseModelProvider,
        world_state: WorldStateService,
        quests: QuestService,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.world_state = world_state
        self.quests = quests
        self.settings = settings or get_settings()

    async def judge_turn(
        self,
        db,
        session: ChatSession,
        *,
        user_message: str,
        response_text: str,
        turn_id: str | None = None,
    ) -> tuple[WorldStateLedger | None, list[QuestChange], list[str]]:
        """Run the combined world+quest+suggestions extraction in one call and
        apply each section. Returns ``(new_ledger_row_or_None, quest_changes,
        suggestions)``.

        Best-effort: provider/schema/apply failures are logged + metered and
        skipped, never raised."""
        do_world = world_state_on(session, self.settings)
        do_quests = quests_on(session, self.settings) and (
            session.turn_count % self.settings.quest_extraction_interval == 0
        )
        do_suggestions = bool(session.suggestions_enabled)
        if not do_world and not do_quests and not do_suggestions:
            return None, [], []

        with tracer.start_as_current_span("orchestrator.post_turn_judge") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            span.set_attribute(
                "rpg.post_turn.sections",
                ",".join(
                    name
                    for name, on in (("world", do_world), ("quests", do_quests), ("suggestions", do_suggestions))
                    if on
                ),
            )

            # --- context for the prompt + the apply paths ------------------
            ledger = None
            base_version: int | None = None
            quest_objs: list[Quest] = []
            reserved_slugs: set[str] = set()
            parts: list[str] = []
            if do_world:
                ledger = await self.world_state.load_current(db, session.id)
                base_version = await self.world_state.current_version(db, session.id)
                parts.append(f"CURRENT LEDGER:\n{ledger.model_dump_json()}")
            if do_quests:
                quest_objs, reserved_slugs = await self.quests.load_open_and_reserved(db, session)
                open_json = [
                    {
                        "slug": q.slug,
                        "title": q.title,
                        "quest_type": q.quest_type,
                        "description": q.description,
                        "status": q.status,
                        "stages": q.stages,
                    }
                    for q in quest_objs
                ]
                parts.append(f"OPEN QUESTS:\n{open_json}")
            parts.append(f"LATEST EXCHANGE:\nPLAYER: {user_message}\nRESPONSE: {response_text}")
            user_content = "\n\n".join(parts)

            system_prompt = build_post_turn_judge_prompt(world=do_world, quests=do_quests, suggestions=do_suggestions)
            post_turn_judge_calls.add(1)
            try:
                payload = await self.provider.generate_json(
                    [
                        ProviderMessage(role="system", content=system_prompt),
                        ProviderMessage(role="user", content=user_content),
                    ],
                    temperature=0.1,
                    max_tokens=self.settings.post_turn_judge_max_tokens,
                )
            except ProviderError as exc:
                logger.exception("post-turn judge failed for session=%s", session.id)
                record_span_error(span, exc)
                return None, [], []

            if not isinstance(payload, dict):
                logger.warning("post-turn judge returned non-object for session=%s", session.id)
                return None, [], []
            set_completion(span, json.dumps(payload))

            world_raw, quest_raw = self._split_sections(payload, world=do_world, quests=do_quests)

            new_ledger = (
                await self._apply_world(db, session, world_raw, ledger, base_version, turn_id) if do_world else None
            )
            quest_changes = (
                await self._apply_quests(db, session, quest_raw, quest_objs, reserved_slugs, turn_id)
                if do_quests
                else []
            )
            suggestions = self._extract_suggestions(payload) if do_suggestions else []
            return new_ledger, quest_changes, suggestions

    async def suggest_only(
        self,
        session: ChatSession,
        *,
        user_message: str,
        response_text: str,
    ) -> list[str]:
        """Generate suggested next-action chips for one exchange — nothing else.

        Used when reopening a chronicle to regenerate ephemeral chips for the
        latest reply. Deliberately runs no world/quest extraction, so a reload
        never mutates canon. Best-effort: any failure yields ``[]``."""
        if not session.suggestions_enabled:
            return []
        with tracer.start_as_current_span("orchestrator.post_turn_judge") as span:
            span.set_attribute("rpg.session_id", str(session.id))
            span.set_attribute("rpg.post_turn.sections", "suggestions")
            system_prompt = build_post_turn_judge_prompt(world=False, quests=False, suggestions=True)
            user_content = f"LATEST EXCHANGE:\nPLAYER: {user_message}\nRESPONSE: {response_text}"
            post_turn_judge_calls.add(1)
            try:
                payload = await self.provider.generate_json(
                    [
                        ProviderMessage(role="system", content=system_prompt),
                        ProviderMessage(role="user", content=user_content),
                    ],
                    temperature=0.1,
                    max_tokens=self.settings.post_turn_judge_max_tokens,
                )
            except ProviderError as exc:
                logger.exception("suggestion regeneration failed for session=%s", session.id)
                record_span_error(span, exc)
                return []
            if not isinstance(payload, dict):
                logger.warning("suggestion regeneration returned non-object for session=%s", session.id)
                return []
            set_completion(span, json.dumps(payload))
            return self._extract_suggestions(payload)

    def _extract_suggestions(self, payload: dict) -> list[str]:
        """Pull, clean and clamp the suggestions array. Best-effort: any
        malformed/missing payload yields ``[]``, never raises."""
        raw = payload.get("suggestions")
        if not isinstance(raw, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            text = item.strip()
            # Drop blanks and case-insensitive duplicates — a small model may
            # repeat a chip, which would collide on the React key and silently
            # drop one anyway.
            if not text or text.casefold() in seen:
                continue
            seen.add(text.casefold())
            cleaned.append(text)
            if len(cleaned) >= self.settings.suggestions_max:
                break
        if cleaned:
            post_turn_suggestions.add(len(cleaned))
        return cleaned

    @staticmethod
    def _split_sections(payload: dict, *, world: bool, quests: bool) -> tuple[object, object]:
        """Pull the two section payloads. Tolerates a model that ignored the
        wrapper and returned the inner shape at the top level — but only when a
        single section was requested, so the mapping is unambiguous."""
        world_raw = payload.get("world_delta")
        quest_raw = payload.get("quest_delta")
        if world and not quests and world_raw is None and quest_raw is None:
            world_raw = payload
        if quests and not world and quest_raw is None and world_raw is None:
            quest_raw = payload
        return world_raw, quest_raw

    async def _apply_world(
        self, db, session: ChatSession, raw: object, ledger, base_version: int | None, turn_id: str | None
    ) -> WorldStateLedger | None:
        if not raw:
            return None
        try:
            delta = LedgerDelta.model_validate(raw)
        except ValidationError as exc:
            logger.warning("post-turn judge world delta invalid for session=%s: %s", session.id, exc)
            canon_extract_failures.add(1, {"reason": "schema"})
            return None
        try:
            return await self.world_state.apply_world_delta(
                db, session, delta, ledger=ledger, base_version=base_version, turn_id=turn_id
            )
        except Exception:
            # One bad section must not sink the other (and never the turn).
            logger.exception("post-turn judge world apply failed for session=%s", session.id)
            return None

    async def _apply_quests(
        self,
        db,
        session: ChatSession,
        raw: object,
        quest_objs: list[Quest],
        reserved_slugs: set[str],
        turn_id: str | None,
    ) -> list[QuestChange]:
        if not raw:
            return []
        # Lenient parse: a single malformed item (e.g. a missing slug) drops
        # only that item, not the whole quest section.
        delta = QuestDelta.lenient(raw)
        if delta.is_empty():
            return []
        try:
            return await self.quests.apply_quest_delta(
                db, session, delta, quests=quest_objs, reserved_slugs=reserved_slugs, turn_id=turn_id
            )
        except Exception:
            logger.exception("post-turn judge quest apply failed for session=%s", session.id)
            return []
