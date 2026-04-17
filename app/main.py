from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import CharacterCard, EpisodeSummary, MemoryFact, RelationshipState, Session as ChatSession, WorldState
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
    RelationshipStateResponse,
    SessionInitRequest,
    SessionInitResponse,
    SessionMemoryResponse,
)
from app.providers.base import ProviderError
from app.services.orchestrator import get_orchestrator
from app.config import get_settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="small-rpg-gpt")

# Log startup configuration
_settings = get_settings()
if _settings.dev_mode:
    logger.info("+ DEV MODE ENABLED - model: %s, timeout: %.0fs", _settings.dev_model_name, _settings.request_timeout_seconds)
else:
    logger.info("+ Production mode - Actor: %s, Memory: %s, GM: %s",
                _settings.actor_model_name, _settings.memory_model_name, _settings.gm_model_name)


@app.get("/health", response_model=HealthResponse)
async def health(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        return HealthResponse(status="ok", database="ok")
    except Exception as exc:  # pragma: no cover
        logger.exception("healthcheck failed")
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@app.post("/character/load", response_model=CharacterLoadResponse)
async def load_character(payload: CharacterLoadRequest, db: Session = Depends(get_db)) -> CharacterLoadResponse:
    character = db.query(CharacterCard).filter(CharacterCard.name == payload.name).one_or_none()
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

    world = db.query(WorldState).filter(WorldState.name == payload.world_name).one_or_none()
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

    db.commit()
    db.refresh(character)
    db.refresh(world)

    return CharacterLoadResponse(
        character_card_id=character.id,
        world_state_id=world.id,
        character_name=character.name,
        world_name=world.name,
    )


@app.post("/session/init", response_model=SessionInitResponse)
async def init_session(payload: SessionInitRequest, db: Session = Depends(get_db)) -> SessionInitResponse:
    character = db.query(CharacterCard).filter(CharacterCard.id == payload.character_card_id).one_or_none()
    if character is None:
        raise HTTPException(status_code=404, detail="Character card not found.")

    world = None
    if payload.world_state_id:
        world = db.query(WorldState).filter(WorldState.id == payload.world_state_id).one_or_none()
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
    db.commit()
    db.refresh(session)

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


@app.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
async def get_session_memory(session_id: str, db: Session = Depends(get_db)) -> SessionMemoryResponse:
    session = db.query(ChatSession).filter(ChatSession.id == session_id).one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    facts = db.query(MemoryFact).filter(MemoryFact.session_id == session_id).order_by(MemoryFact.created_at.desc()).all()
    summaries = db.query(EpisodeSummary).filter(EpisodeSummary.session_id == session_id).order_by(EpisodeSummary.created_at.desc()).all()
    relationships = db.query(RelationshipState).filter(RelationshipState.session_id == session_id).order_by(RelationshipState.updated_at.desc()).all()

    return SessionMemoryResponse(
        session_id=session_id,
        facts=[MemoryFactResponse.model_validate(f) for f in facts],
        episode_summaries=[EpisodeSummaryResponse.model_validate(s) for s in summaries],
        relationships=[RelationshipStateResponse.model_validate(r) for r in relationships],
    )


# =============================================================================
# GAME MASTER ENDPOINTS
# =============================================================================


@app.post("/gm/chat", response_model=GMChatResponse)
async def gm_chat(
    payload: GMChatRequest,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
) -> GMNarrationResponse:
    """Generate standalone GM narration for a scene."""
    from sqlalchemy import select
    session = db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id)
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
    db: Session = Depends(get_db),
) -> GMEventCheckResponse:
    """Check if an event should trigger in the current game state."""
    from sqlalchemy import select
    session = db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id)
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
    db: Session = Depends(get_db),
) -> GMEventGenerateResponse:
    """Generate a full event narrative from a seed."""
    from sqlalchemy import select
    session = db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id)
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
    db: Session = Depends(get_db),
) -> GMSceneTransitionResponse:
    """Generate narration for a scene transition."""
    from sqlalchemy import select
    session = db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id)
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
    db: Session = Depends(get_db),
) -> NPCDialogueResponse:
    """Generate dialogue for a specific NPC."""
    from sqlalchemy import select
    session = db.scalar(
        select(ChatSession)
        .options(joinedload(ChatSession.world_state))
        .where(ChatSession.id == payload.session_id)
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
