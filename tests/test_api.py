from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.schemas import (
    ChatResponse,
    GMChatResponse,
    GMEventCheckResponse,
    GMEventGenerateResponse,
    GMNarrationResponse,
    GMSceneTransitionResponse,
    NPCDialogueResponse,
)
from tests.conftest import MockProvider
from tests.factories import (
    CharacterCardFactory,
    SessionFactory,
    WorldStateFactory,
)


# ===========================================================================
# Health
# ===========================================================================


@pytest.mark.asyncio
async def test_health_returns_200(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


# ===========================================================================
# Character
# ===========================================================================


@pytest.mark.asyncio
async def test_load_character_creates_character_and_world(async_client: AsyncClient) -> None:
    payload = {
        "name": "Aria the Bold",
        "description": "A fierce warrior.",
        "hard_rules": ["No killing innocents"],
        "world_name": "Shadowrealm",
        "world_description": "A dark realm.",
        "world_canon": "Magic is forbidden.",
        "world_hard_rules": ["No technology"],
    }
    response = await async_client.post("/character/load", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "character_card_id" in data
    assert "world_state_id" in data
    assert data["character_name"] == "Aria the Bold"
    assert data["world_name"] == "Shadowrealm"


@pytest.mark.asyncio
async def test_load_character_upserts_existing_by_name(async_client: AsyncClient) -> None:
    payload = {
        "name": "Repeated Hero",
        "description": "First description.",
        "hard_rules": [],
        "world_name": "Same World",
        "world_description": "desc",
        "world_canon": "",
        "world_hard_rules": [],
    }
    r1 = await async_client.post("/character/load", json=payload)
    assert r1.status_code == 200
    id1 = r1.json()["character_card_id"]

    payload["description"] = "Updated description."
    r2 = await async_client.post("/character/load", json=payload)
    assert r2.status_code == 200
    assert r2.json()["character_card_id"] == id1  # same ID — upserted


@pytest.mark.asyncio
async def test_load_character_missing_required_fields_returns_422(async_client: AsyncClient) -> None:
    # Missing 'name', 'world_name', 'world_description'
    response = await async_client.post("/character/load", json={"description": "No name."})
    assert response.status_code == 422


# ===========================================================================
# Session
# ===========================================================================


@pytest.mark.asyncio
async def test_init_session_creates_session(async_client: AsyncClient) -> None:
    character = CharacterCardFactory()
    world = WorldStateFactory()

    response = await async_client.post(
        "/session/init",
        json={
            "character_card_id": character.id,
            "world_state_id": world.id,
            "title": "Test Adventure",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["character_card_id"] == character.id
    assert data["title"] == "Test Adventure"


@pytest.mark.asyncio
async def test_init_session_with_gm_enabled(async_client: AsyncClient) -> None:
    character = CharacterCardFactory()
    world = WorldStateFactory()

    response = await async_client.post(
        "/session/init",
        json={
            "character_card_id": character.id,
            "world_state_id": world.id,
            "gm_enabled": True,
            "current_location": "The tavern",
            "time_of_day": "evening",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["gm_enabled"] is True
    assert data["current_location"] == "The tavern"
    assert data["time_of_day"] == "evening"


@pytest.mark.asyncio
async def test_init_session_invalid_character_card_returns_404(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/session/init",
        json={"character_card_id": "nonexistent-id"},
    )
    assert response.status_code == 404


# ===========================================================================
# Chat (mocked orchestrator)
# ===========================================================================


@pytest.mark.asyncio
async def test_chat_returns_reply_and_continuity_info(
    async_client_mocked_orchestrator: tuple[AsyncClient, MagicMock],
) -> None:
    client, mock_orch = async_client_mocked_orchestrator
    session = SessionFactory()

    mock_orch.chat.return_value = ChatResponse(
        session_id=session.id,
        reply="Hello, traveler!",
        continuity_applied=False,
        continuity_issues=[],
        retrieved_memories=[],
    )

    response = await client.post(
        "/chat",
        json={"session_id": session.id, "user_message": "Hello"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Hello, traveler!"
    assert data["continuity_applied"] is False


@pytest.mark.asyncio
async def test_chat_with_invalid_session_returns_error(
    async_client_mocked_orchestrator: tuple[AsyncClient, MagicMock],
) -> None:
    from fastapi import HTTPException

    client, mock_orch = async_client_mocked_orchestrator
    mock_orch.chat.side_effect = HTTPException(status_code=404, detail="Session not found.")

    response = await client.post(
        "/chat",
        json={"session_id": "bad-id", "user_message": "Hello"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_returns_sse_stream(
    async_client_mocked_orchestrator: tuple[AsyncClient, MagicMock],
) -> None:
    client, mock_orch = async_client_mocked_orchestrator
    session = SessionFactory()

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'type': 'chunk', 'content': 'Hello'})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': session.id})}\n\n"

    mock_orch.chat_stream = fake_stream

    response = await client.post(
        "/chat/stream",
        json={"session_id": session.id, "user_message": "Hello"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


# ===========================================================================
# Memory
# ===========================================================================


@pytest.mark.asyncio
async def test_get_session_memory_returns_facts_summaries_relationships(
    async_client: AsyncClient,
) -> None:
    from tests.factories import EpisodeSummaryFactory, MemoryFactFactory

    session = SessionFactory()
    MemoryFactFactory(session=session, content="Fact one.")
    EpisodeSummaryFactory(session=session, content="Summary one.")

    response = await async_client.get(f"/session/{session.id}/memory")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session.id
    assert len(data["facts"]) == 1
    assert data["facts"][0]["content"] == "Fact one."
    assert len(data["episode_summaries"]) == 1
    assert "relationships" in data


@pytest.mark.asyncio
async def test_get_session_memory_empty_session_returns_empty_lists(
    async_client: AsyncClient,
) -> None:
    session = SessionFactory()

    response = await async_client.get(f"/session/{session.id}/memory")
    assert response.status_code == 200
    data = response.json()
    assert data["facts"] == []
    assert data["episode_summaries"] == []
    assert data["relationships"] == []


# ===========================================================================
# GM Endpoints (mocked orchestrator)
# ===========================================================================


@pytest.mark.asyncio
async def test_gm_chat_returns_reply_with_narration(
    async_client_mocked_orchestrator: tuple[AsyncClient, MagicMock],
) -> None:
    from app.schemas import GMEventGenerateResponse

    client, mock_orch = async_client_mocked_orchestrator
    session = SessionFactory()

    mock_orch.gm_chat.return_value = GMChatResponse(
        session_id=session.id,
        pre_narration="The mist rolls in.",
        character_reply="I draw my sword.",
        post_narration=None,
        event=None,
        continuity_applied=False,
        continuity_issues=[],
        retrieved_memories=[],
    )

    response = await client.post(
        "/gm/chat",
        json={
            "session_id": session.id,
            "user_message": "I look around.",
            "gm_mode": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pre_narration"] == "The mist rolls in."
    assert data["character_reply"] == "I draw my sword."


@pytest.mark.asyncio
async def test_gm_chat_stream_returns_sse_stream(
    async_client_mocked_orchestrator: tuple[AsyncClient, MagicMock],
) -> None:
    client, mock_orch = async_client_mocked_orchestrator
    session = SessionFactory()

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'type': 'done', 'session_id': session.id})}\n\n"

    mock_orch.gm_chat_stream = fake_stream

    response = await client.post(
        "/gm/chat/stream",
        json={"session_id": session.id, "user_message": "I run.", "gm_mode": True},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_gm_narration_returns_narration_text(async_client: AsyncClient) -> None:
    session = SessionFactory()

    from unittest.mock import patch, AsyncMock
    from app.services.orchestrator import get_orchestrator

    mock_orch = MagicMock()
    mock_orch.game_master.generate_narration = AsyncMock(
        return_value="The wind howls through the trees."
    )
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        response = await async_client.post(
            "/gm/narration",
            json={"session_id": session.id, "player_action": "I look around."},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["narration"] == "The wind howls through the trees."


@pytest.mark.asyncio
async def test_gm_event_check_returns_event_check_result(async_client: AsyncClient) -> None:
    session = SessionFactory()

    from unittest.mock import patch, AsyncMock
    from app.services.game_master import EventCheckResult
    from app.services.orchestrator import get_orchestrator

    mock_orch = MagicMock()
    mock_orch.game_master.check_for_event = AsyncMock(
        return_value=EventCheckResult(
            should_trigger=False,
            event_type="none",
            event_seed="",
            urgency="",
            reasoning="Not at interval.",
        )
    )
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        response = await async_client.post(
            "/gm/event/check",
            json={"session_id": session.id, "location": "forest", "time_of_day": "night"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["should_trigger"] is False


@pytest.mark.asyncio
async def test_gm_event_generate_returns_generated_event(async_client: AsyncClient) -> None:
    session = SessionFactory()

    from unittest.mock import patch, AsyncMock
    from app.services.game_master import GeneratedEvent
    from app.services.orchestrator import get_orchestrator

    mock_orch = MagicMock()
    mock_orch.game_master.generate_event = AsyncMock(
        return_value=GeneratedEvent(
            event_type="ambush",
            urgency="immediate",
            description="Bandits leap from the shadows!",
            npcs_involved=["Bandit Leader"],
        )
    )
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        response = await async_client.post(
            "/gm/event/generate",
            json={
                "session_id": session.id,
                "event_seed": "Bandits ambush",
                "event_type": "ambush",
                "urgency": "immediate",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["event_type"] == "ambush"
    assert "Bandits" in data["description"]


@pytest.mark.asyncio
async def test_gm_scene_transition_returns_transition_narration(async_client: AsyncClient) -> None:
    session = SessionFactory()

    from unittest.mock import patch, AsyncMock
    from app.services.game_master import SceneTransition
    from app.services.orchestrator import get_orchestrator

    mock_orch = MagicMock()
    mock_orch.game_master.generate_scene_transition = AsyncMock(
        return_value=SceneTransition(
            narration="You arrive at the dark tavern.",
            time_passed="1 hour",
            new_scene_elements=["dim lighting", "crowded tables"],
        )
    )
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        response = await async_client.post(
            "/gm/scene/transition",
            json={
                "session_id": session.id,
                "previous_scene": "forest road",
                "transition_type": "travel",
                "destination": "The Dark Tavern",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "tavern" in data["narration"].lower()
    assert data["time_passed"] == "1 hour"


@pytest.mark.asyncio
async def test_gm_npc_dialogue_returns_dialogue_text(async_client: AsyncClient) -> None:
    session = SessionFactory()

    from unittest.mock import patch, AsyncMock
    from app.services.orchestrator import get_orchestrator

    mock_orch = MagicMock()
    mock_orch.game_master.generate_npc_dialogue = AsyncMock(
        return_value="What do you want, stranger?"
    )
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        response = await async_client.post(
            "/gm/npc/dialogue",
            json={
                "session_id": session.id,
                "npc_name": "Tavern Keeper",
                "npc_description": "A burly human.",
                "npc_disposition": "neutral",
                "npc_goal": "run the bar",
                "player_statement": "Can I get a room?",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["npc_name"] == "Tavern Keeper"
    assert len(data["dialogue"]) > 0
