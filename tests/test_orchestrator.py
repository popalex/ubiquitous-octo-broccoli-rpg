from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Turn
from app.schemas import ChatResponse, GMChatResponse
from app.services.orchestrator import OrchestratorService
from tests.conftest import MockProvider, make_test_settings
from tests.factories import (
    MemoryFactFactory,
    SessionFactory,
    TurnFactory,
)

EMBEDDING_DIM = 768


@pytest.fixture()
def orchestrator(mock_provider: MockProvider) -> OrchestratorService:
    """OrchestratorService with all providers replaced by MockProvider."""
    settings = make_test_settings(
        memory_summary_interval=100,  # high — prevent accidental refreshes
        retrieval_top_k=8,
        actor_temperature=0.7,
    )
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        svc = OrchestratorService(settings)
    return svc


# ---------------------------------------------------------------------------
# chat — returns ChatResponse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_chat_response(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory()
    await db_session.flush()

    result = await orchestrator.chat(db_session, session.id, "Hello!")
    assert isinstance(result, ChatResponse)
    assert isinstance(result.reply, str)
    assert len(result.reply) > 0
    assert result.session_id == session.id


# ---------------------------------------------------------------------------
# chat — persists user and assistant turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_persists_turns(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory(turn_count=0)
    await db_session.flush()
    session_id = session.id

    await orchestrator.chat(db_session, session_id, "What is happening?")
    db_session.expire_all()

    turns = (await db_session.scalars(
        select(Turn).where(Turn.session_id == session_id).order_by(Turn.turn_index)
    )).all()
    assert len(turns) == 2
    roles = [t.role for t in turns]
    assert "user" in roles
    assert "assistant" in roles
    assert turns[0].content == "What is happening?"


# ---------------------------------------------------------------------------
# chat — triggers memory refresh when threshold is met
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_triggers_memory_refresh_at_threshold(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    # With interval=4 and starting turn_count=2, after chat turn_count=4 → refresh
    settings = make_test_settings(memory_summary_interval=4, retrieval_top_k=8)
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        svc = OrchestratorService(settings)

    session = SessionFactory(turn_count=2, last_summarized_turn=0)
    TurnFactory(session=session, turn_index=1, role="user", content="Turn 1")
    TurnFactory(session=session, turn_index=2, role="assistant", content="Turn 2")
    await db_session.flush()

    mock_provider.set_json_response({
        "ok": True,
        "issues": [],
        "revised_response": "",
    })

    refresh_called = False

    async def spy_refresh(db, session):  # noqa: ARG001
        nonlocal refresh_called
        refresh_called = True
        # override to avoid a second generate_json call
        from app.services.memory import MemoryRefreshResult
        return MemoryRefreshResult(summary_created=False, facts_written=0, relationships_written=0)

    svc.memory.maybe_refresh = spy_refresh  # type: ignore[method-assign]

    await svc.chat(db_session, session.id, "New message")
    assert refresh_called, "Memory refresh was not called when threshold was met"


# ---------------------------------------------------------------------------
# chat — retrieves relevant memories and includes them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_retrieves_memories(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory()
    MemoryFactFactory(session=session, content="The hero has a magic sword.", importance=0.9)
    await db_session.flush()

    result = await orchestrator.chat(db_session, session.id, "What weapon do I have?")
    assert len(result.retrieved_memories) >= 1
    assert any(m.content == "The hero has a magic sword." for m in result.retrieved_memories)


# ---------------------------------------------------------------------------
# chat — applies continuity correction when issues are found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_applies_continuity_correction(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    settings = make_test_settings(memory_summary_interval=100)
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        svc = OrchestratorService(settings)

    session = SessionFactory()
    await db_session.flush()

    mock_provider.set_text_response("I cast a fireball!")  # draft reply
    mock_provider.set_json_response({
        "ok": False,
        "issues": ["Character cannot use magic"],
        "revised_response": "I swing my sword instead.",
    })

    result = await svc.chat(db_session, session.id, "Fight the goblin!")
    assert result.continuity_applied is True
    assert result.reply == "I swing my sword instead."
    assert "Character cannot use magic" in result.continuity_issues


# ---------------------------------------------------------------------------
# chat_stream — yields SSE chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_yields_sse_chunks(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory()
    await db_session.flush()

    chunks = []
    async for chunk in orchestrator.chat_stream(db_session, session.id, "Hello!"):
        chunks.append(chunk)

    assert len(chunks) > 0
    # All chunks should be SSE lines
    assert all(c.startswith("data: ") for c in chunks)
    # Should have a 'done' chunk at the end
    last_data = json.loads(chunks[-1].removeprefix("data: ").strip())
    assert last_data.get("type") == "done"


# ---------------------------------------------------------------------------
# gm_chat — returns GMChatResponse with narration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gm_chat_returns_gm_chat_response(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory(gm_enabled=True, turn_count=0)
    await db_session.flush()

    result = await orchestrator.gm_chat(db_session, session.id, "I look around the room.")
    assert isinstance(result, GMChatResponse)
    assert isinstance(result.character_reply, str)
    assert len(result.character_reply) > 0


# ---------------------------------------------------------------------------
# gm_chat — triggers event generation when event check fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gm_chat_triggers_event_generation(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    settings = make_test_settings(
        memory_summary_interval=100,
        event_check_interval=3,
        event_probability=1.0,
    )
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        svc = OrchestratorService(settings)

    session = SessionFactory(gm_enabled=True, turn_count=3)
    await db_session.flush()

    call_count = 0

    async def alternating_json(messages, *, temperature, max_tokens):
        nonlocal call_count
        call_count += 1
        # First call: event check
        if call_count == 1:
            return {
                "should_trigger": True,
                "event_type": "ambush",
                "event_seed": "Bandits appear.",
                "urgency": "immediate",
                "reasoning": "Right moment.",
            }
        # Second call: continuity check
        return {"ok": True, "issues": [], "revised_response": ""}

    mock_provider.generate_json = alternating_json

    result = await svc.gm_chat(db_session, session.id, "I enter the forest.", location="forest")
    assert result.event is not None
    assert result.event.event_type == "ambush"


# ---------------------------------------------------------------------------
# gm_chat — persists GM narration and event turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gm_chat_persists_turns(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory(gm_enabled=True, turn_count=0)
    await db_session.flush()
    session_id = session.id

    await orchestrator.gm_chat(db_session, session_id, "I explore the dungeon.")
    db_session.expire_all()

    turns = (await db_session.scalars(
        select(Turn).where(Turn.session_id == session_id).order_by(Turn.turn_index)
    )).all()
    # At minimum: user turn + assistant (character) turn; possibly a GM narration turn too
    assert len(turns) >= 2
    roles = {t.role for t in turns}
    assert "user" in roles
    assert "assistant" in roles


# ---------------------------------------------------------------------------
# gm_chat_stream — yields SSE chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gm_chat_stream_yields_sse_chunks(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    session = SessionFactory(gm_enabled=True, turn_count=0)
    await db_session.flush()

    chunks = []
    async for chunk in orchestrator.gm_chat_stream(db_session, session.id, "I run away!"):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert all(c.startswith("data: ") for c in chunks)
    last_data = json.loads(chunks[-1].removeprefix("data: ").strip())
    assert last_data.get("type") == "done"


# ---------------------------------------------------------------------------
# missing session raises 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_missing_session_raises_404(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await orchestrator.chat(db_session, "nonexistent-session-id", "Hello")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# token budget respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_budget_respected(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    """With a tiny context budget, only required sections should appear."""
    settings = make_test_settings(
        actor_max_input_tokens=50,
        actor_reserved_output_tokens=10,
        memory_summary_interval=100,
    )
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        svc = OrchestratorService(settings)

    session = SessionFactory()
    # Add a very long memory fact that should be excluded due to budget
    long_content = "Very important memory: " + "word " * 200
    MemoryFactFactory(session=session, content=long_content, importance=0.9)
    await db_session.flush()

    # Should not raise — the budget capping should keep it from blowing up
    result = await svc.chat(db_session, session.id, "What do I know?")
    assert isinstance(result, ChatResponse)


# ---------------------------------------------------------------------------
# World-state ledger integration (flag on/off)
# ---------------------------------------------------------------------------


def _world_state_orchestrator(mock_provider: MockProvider) -> OrchestratorService:
    settings = make_test_settings(memory_summary_interval=100, world_state_enabled=True)
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        return OrchestratorService(settings)


@pytest.mark.asyncio
async def test_chat_writes_ledger_when_flag_on(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    from app.models import WorldStateLedger

    orchestrator = _world_state_orchestrator(mock_provider)
    # Same payload serves continuity (passes through) and extraction (a death).
    mock_provider.set_json_response({"entities_upsert": [{"id": "kael", "name": "Kael", "status": "dead"}]})
    session = SessionFactory(turn_count=0)
    await db_session.flush()

    await orchestrator.chat(db_session, session.id, "I slay Kael.")

    rows = (await db_session.scalars(
        select(WorldStateLedger).where(WorldStateLedger.session_id == session.id)
    )).all()
    assert len(rows) == 1
    assert rows[0].version == 1
    assert rows[0].state["entities"][0]["status"] == "dead"


@pytest.mark.asyncio
async def test_chat_no_ledger_when_flag_off(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    from app.models import WorldStateLedger

    session = SessionFactory(turn_count=0)
    await db_session.flush()
    await orchestrator.chat(db_session, session.id, "I slay Kael.")

    rows = (await db_session.scalars(
        select(WorldStateLedger).where(WorldStateLedger.session_id == session.id)
    )).all()
    assert rows == []


@pytest.mark.asyncio
async def test_established_death_is_injected_next_turn(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    orchestrator = _world_state_orchestrator(mock_provider)
    mock_provider.set_json_response({"entities_upsert": [{"id": "kael", "name": "Kael", "status": "dead"}]})
    session = SessionFactory(turn_count=0)
    await db_session.flush()
    await orchestrator.chat(db_session, session.id, "I slay Kael.")
    await db_session.refresh(session)

    block = await orchestrator._world_state_block(db_session, session)
    assert "Dead (must stay dead): Kael" in block


# ---------------------------------------------------------------------------
# Quest integration (flag on/off)
# ---------------------------------------------------------------------------


def _quest_orchestrator(mock_provider: MockProvider) -> OrchestratorService:
    settings = make_test_settings(memory_summary_interval=100, quests_enabled=True)
    with patch("app.services.orchestrator.build_provider", return_value=mock_provider):
        return OrchestratorService(settings)


_QUEST_DELTA = {
    "quests_new": [
        {
            "slug": "find-marens-sister",
            "title": "Find Maren's Sister",
            "quest_type": "promise",
            "description": "You promised Maren to find her sister.",
            "stakes": "She is lost forever.",
            "stages": [{"id": "ask-around", "description": "Ask around"}],
        }
    ]
}


@pytest.mark.asyncio
async def test_chat_writes_quest_when_flag_on(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    from app.models import Quest

    orchestrator = _quest_orchestrator(mock_provider)
    # generate_json is called for continuity first, then the quest judge.
    mock_provider.set_json_responses([
        {"ok": True, "issues": [], "revised_response": ""},
        _QUEST_DELTA,
    ])
    session = SessionFactory(turn_count=0)
    await db_session.flush()

    result = await orchestrator.chat(db_session, session.id, "I'll find your sister, Maren.")

    rows = (await db_session.scalars(
        select(Quest).where(Quest.session_id == session.id)
    )).all()
    assert len(rows) == 1
    assert rows[0].slug == "find-marens-sister"
    assert len(result.quest_updates) == 1
    assert result.quest_updates[0].change == "started"


@pytest.mark.asyncio
async def test_chat_no_quest_when_flag_off(
    orchestrator: OrchestratorService, db_session: AsyncSession
) -> None:
    from app.models import Quest

    session = SessionFactory(turn_count=0)
    await db_session.flush()
    await orchestrator.chat(db_session, session.id, "I'll find your sister, Maren.")

    rows = (await db_session.scalars(
        select(Quest).where(Quest.session_id == session.id)
    )).all()
    assert rows == []


@pytest.mark.asyncio
async def test_chat_survives_quest_extraction_failure(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    orchestrator = _quest_orchestrator(mock_provider)
    session = SessionFactory(turn_count=0)
    await db_session.flush()

    async def boom(*args, **kwargs):
        raise RuntimeError("quest judge exploded")

    orchestrator.quests.extract_and_apply = boom  # type: ignore[method-assign]

    result = await orchestrator.chat(db_session, session.id, "Hello!")
    assert isinstance(result, ChatResponse)
    assert result.quest_updates == []


@pytest.mark.asyncio
async def test_chat_stream_emits_quest_update_before_done(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    orchestrator = _quest_orchestrator(mock_provider)
    # chat_stream skips continuity, so the judge gets the only generate_json call.
    mock_provider.set_json_response(_QUEST_DELTA)
    session = SessionFactory(turn_count=0)
    await db_session.flush()

    chunks = []
    async for chunk in orchestrator.chat_stream(db_session, session.id, "I'll find her."):
        chunks.append(chunk)

    events = [json.loads(c.removeprefix("data: ").strip()) for c in chunks]
    types = [e.get("type") for e in events]
    assert "quest_update" in types
    assert types.index("quest_update") < types.index("done")
    quest_event = events[types.index("quest_update")]
    assert quest_event["quest"]["slug"] == "find-marens-sister"
    assert quest_event["quest"]["change"] == "started"


@pytest.mark.asyncio
async def test_gm_chat_injects_quest_block_into_context(
    mock_provider: MockProvider, db_session: AsyncSession
) -> None:
    from tests.factories import QuestFactory

    orchestrator = _quest_orchestrator(mock_provider)
    session = SessionFactory(gm_enabled=True, turn_count=1)  # 1 % 3 != 0: no event check
    QuestFactory(session=session, slug="stop-the-cult", title="Stop the Cult", quest_type="threat")
    await db_session.flush()

    captured: list[str] = []
    original = mock_provider.generate_text

    async def capture(messages, **kwargs):
        captured.append("\n".join(m.content for m in messages))
        return await original(messages, **kwargs)

    mock_provider.generate_text = capture  # type: ignore[method-assign]

    await orchestrator.gm_chat(db_session, session.id, "I sharpen my blade.")
    assert any("Stop the Cult" in text for text in captured)
