from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CharacterCard, EpisodeSummary, MemoryFact, RelationshipState, Session as ChatSession, WorldState
from app.schemas import CharacterLoadRequest, CharacterLoadResponse, ChatRequest, ChatResponse, EpisodeSummaryResponse, HealthResponse, MemoryFactResponse, RelationshipStateResponse, SessionInitRequest, SessionInitResponse, SessionMemoryResponse
from app.providers.base import ProviderError
from app.services.orchestrator import get_orchestrator


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="small-rpg-gpt")


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
