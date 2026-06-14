"""Rewind & fork (TODO §4a).

Forking copies a session up to a chosen turn into a brand-new, independent
chronicle. The parent is **never mutated** — this is fork-only, no destructive
rewind, so we never cascade-delete across turns/memories/summaries/ledger
versions (the decision in TODO.md §4a).

A fork is *full fidelity*: turns ≤ N, the memory facts / episode summaries
derived from them, relationship states, the world-state ledger version current
at N, and quests created ≤ N are all copied. Rows that reference a turn carry a
remapped ``turn_id`` (old → new); references to dropped turns (index > N) become
NULL. Embeddings are copied verbatim — no re-embedding.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import telemetry
from app.models import (
    EpisodeSummary,
    MemoryFact,
    Quest,
    RelationshipState,
    Session,
    Turn,
    WorldStateLedger,
    new_id,
)


class ForkService:
    """Copies a session into an independent fork at a given turn index."""

    @staticmethod
    async def fork_session(db: AsyncSession, parent: Session, at_turn: int, title: str | None = None) -> Session:
        """Create and persist a fork of ``parent`` containing state up to and
        including turn index ``at_turn``. Returns the new (committed) session.

        Caller is responsible for validating ``at_turn`` against the parent's
        turn range and committing nothing beforehand that should not be in the
        fork's transaction.
        """
        kept_turn_ids: set[str] = set()
        id_map: dict[str, str] = {}  # old turn id -> new turn id

        with telemetry.tracer.start_as_current_span("fork.session") as span:
            span.set_attribute("rpg.session.parent_id", parent.id)
            span.set_attribute("rpg.fork.at_turn", at_turn)

            fork = Session(
                character_card_id=parent.character_card_id,
                world_state_id=parent.world_state_id,
                title=title if title is not None else _default_fork_title(parent, at_turn),
                status="active",
                turn_count=at_turn,
                # Summaries ≤ N are copied, so the fork inherits the parent's
                # summarization watermark (capped at the fork point).
                last_summarized_turn=min(parent.last_summarized_turn, at_turn),
                metadata_json=parent.metadata_json,
                gm_enabled=parent.gm_enabled,
                current_location=parent.current_location,
                time_of_day=parent.time_of_day,
                last_event_turn=min(parent.last_event_turn, at_turn),
                world_state_enabled=parent.world_state_enabled,
                quests_enabled=parent.quests_enabled,
                parent_session_id=parent.id,
                forked_at_turn=at_turn,
            )
            db.add(fork)
            await db.flush()  # assign fork.id before we attach children

            # --- turns ≤ N (remap ids) ---
            turns = (
                await db.scalars(
                    select(Turn)
                    .where(Turn.session_id == parent.id, Turn.turn_index <= at_turn)
                    .order_by(Turn.turn_index.asc())
                )
            ).all()
            for t in turns:
                new_turn_id = new_id()
                id_map[t.id] = new_turn_id
                kept_turn_ids.add(t.id)
                db.add(
                    Turn(
                        id=new_turn_id,
                        session_id=fork.id,
                        turn_index=t.turn_index,
                        role=t.role,
                        content=t.content,
                        token_estimate=t.token_estimate,
                        continuity_notes=t.continuity_notes,
                        retcon_note=t.retcon_note,
                        turn_type=t.turn_type,
                    )
                )
            # Persist turns before the rows that FK-reference them: MemoryFact /
            # WorldStateLedger / Quest carry a raw source/turn id column with no
            # ORM relationship, so the unit-of-work can't order them after turns.
            await db.flush()

            # --- memory facts derived from kept turns (or sourceless) ---
            facts = (
                await db.scalars(select(MemoryFact).where(MemoryFact.session_id == parent.id))
            ).all()
            for f in facts:
                if f.source_turn_id is not None and f.source_turn_id not in kept_turn_ids:
                    continue  # produced by a turn after the fork point
                db.add(
                    MemoryFact(
                        session_id=fork.id,
                        character_card_id=f.character_card_id,
                        source_turn_id=id_map.get(f.source_turn_id) if f.source_turn_id else None,
                        content=f.content,
                        importance=f.importance,
                        embedding=f.embedding,
                        metadata_json=f.metadata_json,
                    )
                )

            # --- episode summaries fully within the kept range ---
            summaries = (
                await db.scalars(
                    select(EpisodeSummary).where(
                        EpisodeSummary.session_id == parent.id,
                        EpisodeSummary.end_turn_index <= at_turn,
                    )
                )
            ).all()
            for s in summaries:
                db.add(
                    EpisodeSummary(
                        session_id=fork.id,
                        start_turn_index=s.start_turn_index,
                        end_turn_index=s.end_turn_index,
                        content=s.content,
                        importance=s.importance,
                        embedding=s.embedding,
                        metadata_json=s.metadata_json,
                    )
                )

            # --- relationship states (cumulative; remap last_observed_turn_id) ---
            relationships = (
                await db.scalars(select(RelationshipState).where(RelationshipState.session_id == parent.id))
            ).all()
            for r in relationships:
                last_observed = (
                    id_map.get(r.last_observed_turn_id)
                    if r.last_observed_turn_id in kept_turn_ids
                    else None
                )
                db.add(
                    RelationshipState(
                        session_id=fork.id,
                        source_entity=r.source_entity,
                        target_entity=r.target_entity,
                        status=r.status,
                        notes=r.notes,
                        importance=r.importance,
                        last_observed_turn_id=last_observed,
                    )
                )

            # --- world-state ledger version current at N -> new version 1 ---
            ledger = await _ledger_at(db, parent.id, kept_turn_ids)
            if ledger is not None:
                db.add(
                    WorldStateLedger(
                        session_id=fork.id,
                        version=1,
                        turn_id=id_map.get(ledger.turn_id) if ledger.turn_id else None,
                        state=ledger.state,
                    )
                )

            # --- quests created ≤ N (remap source_turn_id) ---
            quests = (
                await db.scalars(
                    select(Quest).where(Quest.session_id == parent.id, Quest.created_turn <= at_turn)
                )
            ).all()
            for q in quests:
                db.add(
                    Quest(
                        session_id=fork.id,
                        slug=q.slug,
                        title=q.title,
                        quest_type=q.quest_type,
                        description=q.description,
                        stakes=q.stakes,
                        status=q.status,
                        origin=q.origin,
                        stages=q.stages,
                        resolution=q.resolution,
                        created_turn=q.created_turn,
                        accepted_turn=q.accepted_turn,
                        last_progress_turn=q.last_progress_turn,
                        last_escalation_turn=q.last_escalation_turn,
                        resolved_turn=q.resolved_turn,
                        source_turn_id=id_map.get(q.source_turn_id) if q.source_turn_id else None,
                    )
                )

            await db.commit()
            await db.refresh(fork)

            telemetry.session_forks.add(1)
            span.set_attribute("rpg.fork.session_id", fork.id)
            span.set_attribute("rpg.fork.turns_copied", len(turns))
            return fork


async def _ledger_at(
    db: AsyncSession, session_id: str, kept_turn_ids: set[str]
) -> WorldStateLedger | None:
    """The latest ledger version produced at or before the fork point — i.e. the
    highest-version row whose producing turn is kept (or that has no turn_id,
    e.g. a backfill/manual edit)."""
    rows = (
        await db.scalars(
            select(WorldStateLedger)
            .where(WorldStateLedger.session_id == session_id)
            .order_by(WorldStateLedger.version.desc())
        )
    ).all()
    for row in rows:
        if row.turn_id is None or row.turn_id in kept_turn_ids:
            return row
    return None


def _default_fork_title(parent: Session, at_turn: int) -> str:
    base = parent.title or "Chronicle"
    return f"{base} (fork @ turn {at_turn})"
