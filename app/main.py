from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.db import get_db
from app.models import (
    CharacterCard,
    EpisodeSummary,
    MemoryFact,
    Quest,
    RelationshipState,
    Turn,
    WorldState,
    WorldStateLedger,
)
from app.models import Session as ChatSession
from app.providers.base import ProviderError
from app.schemas import (
    CharacterLoadRequest,
    CharacterLoadResponse,
    ChatRequest,
    ChatResponse,
    EpisodeSummaryResponse,
    GMChatRequest,
    GMChatResponse,
    GMEventCheckRequest,
    GMEventCheckResponse,
    GMEventGenerateRequest,
    GMEventGenerateResponse,
    GMNarrationRequest,
    GMNarrationResponse,
    GMSceneTransitionRequest,
    GMSceneTransitionResponse,
    HealthResponse,
    MemoryFactResponse,
    NPCDialogueRequest,
    NPCDialogueResponse,
    QuestPatchRequest,
    QuestResponse,
    RelationshipStateResponse,
    SessionDetailResponse,
    SessionInitRequest,
    SessionInitResponse,
    SessionListItem,
    SessionListResponse,
    SessionMemoryResponse,
    SessionQuestsResponse,
    TurnResponse,
    WorldStateResponse,
)
from app.services.orchestrator import get_orchestrator
from app.services.quests import TERMINAL_STATUSES
from app.telemetry import quest_updates, setup_telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: log the active configuration.
    settings = get_settings()
    if settings.dev_mode:
        logger.info("+ DEV MODE ENABLED - model: %s, timeout: %.0fs, world_state: %s, quests: %s", settings.dev_model_name, settings.request_timeout_seconds, "on" if settings.world_state_enabled else "off", "on" if settings.quests_enabled else "off")
    else:
        logger.info("+ Production mode - Actor: %s, Memory: %s, GM: %s, world_state: %s, quests: %s",
                    settings.actor_model_name, settings.memory_model_name, settings.gm_model_name,
                    "on" if settings.world_state_enabled else "off",
                    "on" if settings.quests_enabled else "off")

    yield

    # Shutdown: close provider HTTP clients, but only if the (lazily built,
    # @lru_cache'd) orchestrator was ever constructed — don't spin one up just
    # to tear it down.
    if get_orchestrator.cache_info().currsize:
        await get_orchestrator().aclose()


app = FastAPI(title="small-rpg-gpt", lifespan=lifespan)
setup_telemetry(app)


@app.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    try:
        await db.execute(text("SELECT 1"))
        return HealthResponse(
            status="ok",
            database="ok",
            mode="DEV" if settings.dev_mode else "PROD",
            world_state_enabled=settings.world_state_enabled,
            quests_enabled=settings.quests_enabled,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("healthcheck failed")
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@app.post("/character/load", response_model=CharacterLoadResponse)
async def load_character(payload: CharacterLoadRequest, db: AsyncSession = Depends(get_db)) -> CharacterLoadResponse:
    character = await db.scalar(select(CharacterCard).where(CharacterCard.name == payload.name))
    if character is None:
        character = CharacterCard(
            name=payload.name,
            description=payload.description,
            hard_rules="\n".join(payload.hard_rules),
            style_guide=payload.style_guide,
        )
        db.add(character)
    else:
        character.description = payload.description
        character.hard_rules = "\n".join(payload.hard_rules)
        character.style_guide = payload.style_guide

    world = await db.scalar(select(WorldState).where(WorldState.name == payload.world_name))
    if world is None:
        world = WorldState(
            name=payload.world_name,
            description=payload.world_description,
            canon=payload.world_canon,
            hard_rules="\n".join(payload.world_hard_rules),
        )
        db.add(world)
    else:
        world.description = payload.world_description
        world.canon = payload.world_canon
        world.hard_rules = "\n".join(payload.world_hard_rules)

    await db.commit()
    await db.refresh(character)
    await db.refresh(world)

    return CharacterLoadResponse(
        character_card_id=character.id,
        world_state_id=world.id,
        character_name=character.name,
        world_name=world.name,
    )


@app.post("/session/init", response_model=SessionInitResponse)
async def init_session(payload: SessionInitRequest, db: AsyncSession = Depends(get_db)) -> SessionInitResponse:
    character = await db.scalar(select(CharacterCard).where(CharacterCard.id == payload.character_card_id))
    if character is None:
        raise HTTPException(status_code=404, detail="Character card not found.")

    world = None
    if payload.world_state_id:
        world = await db.scalar(select(WorldState).where(WorldState.id == payload.world_state_id))
        if world is None:
            raise HTTPException(status_code=404, detail="World state not found.")

    session = ChatSession(
        character_card_id=character.id,
        world_state_id=world.id if world else None,
        title=payload.title,
        gm_enabled=payload.gm_enabled,
        current_location=payload.current_location,
        time_of_day=payload.time_of_day,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return SessionInitResponse(
        session_id=session.id,
        character_card_id=session.character_card_id,
        world_state_id=session.world_state_id,
        title=session.title,
        turn_count=session.turn_count,
        gm_enabled=session.gm_enabled,
        current_location=session.current_location,
        time_of_day=session.time_of_day,
    )


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(db: AsyncSession = Depends(get_db)) -> SessionListResponse:
    sessions = (await db.scalars(
        select(ChatSession)
        .where(ChatSession.status != "archived")
        .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
        .order_by(ChatSession.updated_at.desc())
    )).all()
    items = []
    for s in sessions:
        latest_summary = await db.scalar(
            select(EpisodeSummary)
            .where(EpisodeSummary.session_id == s.id)
            .order_by(EpisodeSummary.created_at.desc())
            .limit(1)
        )
        summary: str | None = None
        if latest_summary:
            summary = latest_summary.content[:200]
        else:
            last_turn = await db.scalar(
                select(Turn)
                .where(Turn.session_id == s.id, Turn.role == "assistant")
                .order_by(Turn.turn_index.desc())
                .limit(1)
            )
            if last_turn:
                summary = last_turn.content[:200]
        items.append(SessionListItem(
            id=s.id,
            title=s.title,
            status=s.status,
            gm_enabled=s.gm_enabled,
            turn_count=s.turn_count,
            created_at=s.created_at,
            updated_at=s.updated_at,
            character_card_id=s.character_card_id,
            world_state_id=s.world_state_id,
            character_name=s.character_card.name if s.character_card else None,
            world_name=s.world_state.name if s.world_state else None,
            summary=summary,
        ))
    return SessionListResponse(sessions=items)


@app.get("/session/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> SessionDetailResponse:
    session = await db.scalar(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        status=session.status,
        gm_enabled=session.gm_enabled,
        turn_count=session.turn_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        character_card_id=session.character_card_id,
        world_state_id=session.world_state_id,
        character_name=session.character_card.name if session.character_card else None,
        world_name=session.world_state.name if session.world_state else None,
        current_location=session.current_location,
        time_of_day=session.time_of_day,
    )


@app.get("/session/{session_id}/turns", response_model=list[TurnResponse])
async def get_session_turns(session_id: str, db: AsyncSession = Depends(get_db)) -> list[TurnResponse]:
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    turns = (await db.scalars(
        select(Turn)
        .where(Turn.session_id == session_id)
        .order_by(Turn.turn_index.asc())
    )).all()
    return [TurnResponse.model_validate(t) for t in turns]


@app.delete("/session/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)) -> None:
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await db.delete(session)
    await db.commit()


@app.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    try:
        orchestrator = get_orchestrator()
        return await orchestrator.chat(db, payload.session_id, payload.user_message)
    except (RuntimeError, ProviderError) as exc:
        logger.exception("chat failed for session=%s", payload.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream chat response as Server-Sent Events (SSE)."""
    orchestrator = get_orchestrator()
    return StreamingResponse(
        orchestrator.chat_stream(db, payload.session_id, payload.user_message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/session/{session_id}/memory", response_model=SessionMemoryResponse)
async def get_session_memory(session_id: str, db: AsyncSession = Depends(get_db)) -> SessionMemoryResponse:
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    summaries = (await db.scalars(
        select(EpisodeSummary)
        .where(EpisodeSummary.session_id == session_id)
        .order_by(EpisodeSummary.created_at.desc())
    )).all()

    # Delete broken placeholder summaries left by the old bug so we can regenerate.
    placeholder_ids = [s.id for s in summaries if s.content.strip() == "No summary produced."]
    if placeholder_ids:
        logger.info("backfill_summary CLEANUP session=%s removing %s placeholder summaries", session_id, len(placeholder_ids))
        await db.execute(delete(EpisodeSummary).where(EpisodeSummary.id.in_(placeholder_ids)))
        session.last_summarized_turn = 0
        await db.commit()
        summaries = [s for s in summaries if s.id not in placeholder_ids]

    # If no valid summaries exist but there are unsummarized turns, backfill now.
    if not summaries and session.turn_count > session.last_summarized_turn:
        logger.info(
            "backfill_summary START session=%s turn_count=%s last_summarized=%s",
            session_id, session.turn_count, session.last_summarized_turn,
        )
        try:
            orchestrator = get_orchestrator()
            result = await orchestrator.memory.maybe_refresh(db, session, force=True)
            summaries = (await db.scalars(
                select(EpisodeSummary)
                .where(EpisodeSummary.session_id == session_id)
                .order_by(EpisodeSummary.created_at.desc())
            )).all()
            logger.info(
                "backfill_summary DONE session=%s summary_created=%s facts=%s relationships=%s summaries_now=%s",
                session_id, result.summary_created, result.facts_written, result.relationships_written, len(summaries),
            )
        except Exception:
            logger.exception("backfill summary failed for session=%s", session_id)

    facts = (await db.scalars(
        select(MemoryFact)
        .where(MemoryFact.session_id == session_id)
        .order_by(MemoryFact.created_at.desc())
    )).all()
    relationships = (await db.scalars(
        select(RelationshipState)
        .where(RelationshipState.session_id == session_id)
        .order_by(RelationshipState.updated_at.desc())
    )).all()

    return SessionMemoryResponse(
        session_id=session_id,
        facts=[MemoryFactResponse.model_validate(f) for f in facts],
        episode_summaries=[EpisodeSummaryResponse.model_validate(s) for s in summaries],
        relationships=[RelationshipStateResponse.model_validate(r) for r in relationships],
    )


@app.get("/session/{session_id}/world-state", response_model=WorldStateResponse)
async def get_world_state(
    session_id: str,
    version: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> WorldStateResponse:
    """Return the current world-state ledger for a session (or a specific
    historical ``?version=``). Empty ledger (version 0) if none recorded yet."""
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    query = select(WorldStateLedger).where(WorldStateLedger.session_id == session_id)
    if version is not None:
        query = query.where(WorldStateLedger.version == version)
    else:
        query = query.order_by(WorldStateLedger.version.desc())
    row = await db.scalar(query.limit(1))

    if row is None:
        if version is not None:
            raise HTTPException(status_code=404, detail="World-state version not found.")
        return WorldStateResponse(session_id=session_id, version=0, state={}, created_at=None)

    return WorldStateResponse(
        session_id=session_id,
        version=row.version,
        state=row.state,
        created_at=row.created_at,
    )


@app.get("/session/{session_id}/quests", response_model=SessionQuestsResponse)
async def get_session_quests(
    session_id: str,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> SessionQuestsResponse:
    """Return a session's quests (optionally filtered by ``?status=``),
    open arcs first, most recently touched first. Not gated on
    ``QUESTS_ENABLED`` — arcs tracked while the flag was on stay visible."""
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    query = select(Quest).where(Quest.session_id == session_id)
    if status is not None:
        query = query.where(Quest.status == status)
    quests = (await db.scalars(query.order_by(Quest.updated_at.desc()))).all()
    ordered = sorted(quests, key=lambda q: q.status in TERMINAL_STATUSES)
    return SessionQuestsResponse(
        session_id=session_id,
        quests=[QuestResponse.model_validate(q) for q in ordered],
    )


@app.patch("/session/{session_id}/quests/{quest_id}", response_model=QuestResponse)
async def patch_session_quest(
    session_id: str,
    quest_id: str,
    payload: QuestPatchRequest,
    db: AsyncSession = Depends(get_db),
) -> QuestResponse:
    """Manually abandon a quest. Terminal quests are immutable (409)."""
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    quest = await db.scalar(
        select(Quest).where(Quest.id == quest_id, Quest.session_id == session_id)
    )
    if quest is None:
        raise HTTPException(status_code=404, detail="Quest not found.")
    if quest.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Quest is already concluded.")

    quest.status = payload.status
    quest.resolved_turn = session.turn_count
    quest.resolution = "Abandoned by the player."
    await db.commit()
    await db.refresh(quest)
    quest_updates.add(1, {"change": payload.status})
    return QuestResponse.model_validate(quest)


# =============================================================================
# GAME MASTER ENDPOINTS
# =============================================================================


@app.post("/gm/chat", response_model=GMChatResponse)
async def gm_chat(
    payload: GMChatRequest,
    db: AsyncSession = Depends(get_db),
) -> GMChatResponse:
    """
    GM-driven chat with narration and event generation.

    Wraps the character interaction with world narration and potentially
    triggered events for a richer gameplay experience.
    """
    try:
        orchestrator = get_orchestrator()
        return await orchestrator.gm_chat(
            db,
            payload.session_id,
            payload.user_message,
            location=payload.location,
            time_of_day=payload.time_of_day,
        )
    except (RuntimeError, ProviderError) as exc:
        logger.exception("gm_chat failed for session=%s", payload.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/gm/chat/stream")
async def gm_chat_stream(
    payload: GMChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Streaming GM-driven chat with narration and event generation.

    Streams pre-narration, character reply, and events as they generate.
    """
    orchestrator = get_orchestrator()
    return StreamingResponse(
        orchestrator.gm_chat_stream(
            db,
            payload.session_id,
            payload.user_message,
            location=payload.location,
            time_of_day=payload.time_of_day,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/gm/narration", response_model=GMNarrationResponse)
async def gm_narration(
    payload: GMNarrationRequest,
    db: AsyncSession = Depends(get_db),
) -> GMNarrationResponse:
    """Generate standalone GM narration for a scene."""
    session = await db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        orchestrator = get_orchestrator()
        narration = await orchestrator.game_master.generate_narration(
            world_state=session.world_state,
            recent_events="",  # Could be populated from recent turns if needed
            player_action=payload.player_action,
            scene_context=payload.scene_context or "",
        )
        return GMNarrationResponse(
            session_id=payload.session_id,
            narration=narration,
        )
    except ProviderError as exc:
        logger.exception("gm_narration failed for session=%s", payload.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/gm/event/check", response_model=GMEventCheckResponse)
async def gm_event_check(
    payload: GMEventCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> GMEventCheckResponse:
    """Check if an event should trigger in the current game state."""
    session = await db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.game_master.check_for_event(
            db,
            session,
            location=payload.location,
            time_of_day=payload.time_of_day,
        )
        return GMEventCheckResponse(
            should_trigger=result.should_trigger,
            event_type=result.event_type,
            event_seed=result.event_seed,
            urgency=result.urgency,
            reasoning=result.reasoning,
        )
    except ProviderError as exc:
        logger.exception("gm_event_check failed for session=%s", payload.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/gm/event/generate", response_model=GMEventGenerateResponse)
async def gm_event_generate(
    payload: GMEventGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> GMEventGenerateResponse:
    """Generate a full event narrative from a seed."""
    session = await db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        orchestrator = get_orchestrator()
        event = await orchestrator.game_master.generate_event(
            world_state=session.world_state,
            event_seed=payload.event_seed,
            event_type=payload.event_type,
            urgency=payload.urgency,
            player_actions="",  # Could be populated from recent turns
        )
        return GMEventGenerateResponse(
            event_type=event.event_type,
            urgency=event.urgency,
            description=event.description,
            npcs_involved=event.npcs_involved,
        )
    except ProviderError as exc:
        logger.exception("gm_event_generate failed for session=%s", payload.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/gm/scene/transition", response_model=GMSceneTransitionResponse)
async def gm_scene_transition(
    payload: GMSceneTransitionRequest,
    db: AsyncSession = Depends(get_db),
) -> GMSceneTransitionResponse:
    """Generate narration for a scene transition."""
    session = await db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.game_master.generate_scene_transition(
            world_state=session.world_state,
            previous_scene=payload.previous_scene,
            transition_type=payload.transition_type,
            destination=payload.destination,
        )
        return GMSceneTransitionResponse(
            narration=result.narration,
            time_passed=result.time_passed,
            new_scene_elements=result.new_scene_elements,
        )
    except ProviderError as exc:
        logger.exception("gm_scene_transition failed for session=%s", payload.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/gm/npc/dialogue", response_model=NPCDialogueResponse)
async def gm_npc_dialogue(
    payload: NPCDialogueRequest,
    db: AsyncSession = Depends(get_db),
) -> NPCDialogueResponse:
    """Generate dialogue for a specific NPC."""
    session = await db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        orchestrator = get_orchestrator()
        dialogue = await orchestrator.game_master.generate_npc_dialogue(
            world_state=session.world_state,
            npc_name=payload.npc_name,
            npc_description=payload.npc_description,
            npc_disposition=payload.npc_disposition,
            npc_goal=payload.npc_goal,
            conversation_context="",  # Could be populated from recent turns
            player_statement=payload.player_statement,
        )
        return NPCDialogueResponse(
            npc_name=payload.npc_name,
            dialogue=dialogue,
        )
    except ProviderError as exc:
        logger.exception("gm_npc_dialogue failed for session=%s npc=%s", payload.session_id, payload.npc_name)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
