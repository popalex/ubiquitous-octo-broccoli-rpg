from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.providers.base import ProviderError
from app.services.game_master import (
    EventCheckResult,
    GameMasterService,
    GeneratedEvent,
    SceneTransition,
    WorldStateUpdateResult,
)
from tests.conftest import MockProvider, make_test_settings
from tests.factories import SessionFactory, TurnFactory, WorldStateFactory


@pytest.fixture()
def service(mock_provider: MockProvider) -> GameMasterService:
    settings = make_test_settings(
        event_check_interval=3,
        event_probability=1.0,  # always trigger for tests
    )
    return GameMasterService(mock_provider, settings)


# ---------------------------------------------------------------------------
# generate_narration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_narration_returns_text(service: GameMasterService) -> None:
    world = WorldStateFactory.build()
    narration = await service.generate_narration(
        world_state=world,
        recent_events="The hero entered the cave.",
        player_action="I look around carefully.",
    )
    assert isinstance(narration, str)
    assert len(narration) > 0


# ---------------------------------------------------------------------------
# generate_narration_stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_narration_stream_yields_chunks(service: GameMasterService) -> None:
    world = WorldStateFactory.build()
    chunks = []
    async for chunk in service.generate_narration_stream(
        world_state=world,
        recent_events="",
        player_action="I search the room.",
    ):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert all(isinstance(c, str) for c in chunks)


# ---------------------------------------------------------------------------
# check_for_event — interval not met → should_trigger=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_for_event_false_when_interval_not_met(
    service: GameMasterService, db_session: Session
) -> None:
    settings = make_test_settings(event_check_interval=3, event_probability=1.0)
    svc = GameMasterService(service.gm_provider, settings)
    session = SessionFactory(turn_count=5)  # 5 % 3 != 0
    db_session.flush()

    result = await svc.check_for_event(db_session, session)
    assert result.should_trigger is False


# ---------------------------------------------------------------------------
# check_for_event — valid EventCheckResult when triggered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_for_event_returns_valid_result_when_triggered(
    mock_provider: MockProvider, db_session: Session
) -> None:
    settings = make_test_settings(event_check_interval=3, event_probability=1.0)
    service = GameMasterService(mock_provider, settings)
    session = SessionFactory(turn_count=3)  # 3 % 3 == 0
    db_session.flush()

    mock_provider.set_json_response({
        "should_trigger": True,
        "event_type": "ambush",
        "event_seed": "Bandits attack from the shadows.",
        "urgency": "immediate",
        "reasoning": "Perfect ambush conditions.",
    })

    result = await service.check_for_event(db_session, session)
    assert isinstance(result, EventCheckResult)
    assert result.should_trigger is True
    assert result.event_type == "ambush"
    assert result.urgency == "immediate"


# ---------------------------------------------------------------------------
# generate_event — returns GeneratedEvent with expected fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_event_returns_generated_event(
    mock_provider: MockProvider,
) -> None:
    settings = make_test_settings()
    service = GameMasterService(mock_provider, settings)
    world = WorldStateFactory.build()

    mock_provider.set_text_response("A band of brigands leaps from behind the trees!")

    result = await service.generate_event(
        world_state=world,
        event_seed="Bandits appear",
        event_type="ambush",
        urgency="immediate",
        player_actions="Walking down the forest road.",
    )
    assert isinstance(result, GeneratedEvent)
    assert result.event_type == "ambush"
    assert result.urgency == "immediate"
    assert len(result.description) > 0


# ---------------------------------------------------------------------------
# generate_scene_transition — returns narration, time_passed, new elements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_scene_transition_returns_full_result(
    mock_provider: MockProvider,
) -> None:
    settings = make_test_settings()
    service = GameMasterService(mock_provider, settings)
    world = WorldStateFactory.build()

    mock_provider.set_json_response({
        "narration": "You arrive at the tavern after a long journey.",
        "time_passed": "2 hours",
        "new_scene_elements": ["roaring fireplace", "suspicious patrons"],
    })

    result = await service.generate_scene_transition(
        world_state=world,
        previous_scene="dark forest",
        transition_type="travel",
        destination="The Rusted Flagon tavern",
    )
    assert isinstance(result, SceneTransition)
    assert "tavern" in result.narration.lower()
    assert result.time_passed == "2 hours"
    assert "roaring fireplace" in result.new_scene_elements


# ---------------------------------------------------------------------------
# generate_npc_dialogue — returns dialogue text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_npc_dialogue_returns_text(
    mock_provider: MockProvider,
) -> None:
    settings = make_test_settings()
    service = GameMasterService(mock_provider, settings)
    world = WorldStateFactory.build()

    mock_provider.set_text_response("Aye, I know where the mines are, but I'll not say for free.")

    dialogue = await service.generate_npc_dialogue(
        world_state=world,
        npc_name="Old Grom",
        npc_description="A grizzled dwarf miner.",
        npc_disposition="suspicious",
        npc_goal="protect his secrets",
        conversation_context="The hero just arrived in the village.",
        player_statement="Tell me about the abandoned mines.",
    )
    assert isinstance(dialogue, str)
    assert len(dialogue) > 0


# ---------------------------------------------------------------------------
# analyze_world_state_changes — returns updates, flags_set, flags_cleared
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_world_state_changes_returns_result(
    mock_provider: MockProvider,
) -> None:
    settings = make_test_settings()
    service = GameMasterService(mock_provider, settings)

    mock_provider.set_json_response({
        "updates": [
            {
                "entity": "Dragon",
                "change_type": "killed",
                "old_value": "alive",
                "new_value": "dead",
                "permanence": "permanent",
            }
        ],
        "flags_set": ["dragon_slain"],
        "flags_cleared": ["dragon_threat"],
    })

    result = await service.analyze_world_state_changes(
        events_summary="The dragon was slain by the hero.",
        current_state="Dragon terrorizes the village.",
    )
    assert isinstance(result, WorldStateUpdateResult)
    assert len(result.updates) == 1
    assert result.updates[0].entity == "Dragon"
    assert "dragon_slain" in result.flags_set
    assert "dragon_threat" in result.flags_cleared


# ---------------------------------------------------------------------------
# ProviderError propagates through each method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_error_propagates_from_generate_narration(
    mock_provider: MockProvider,
) -> None:
    settings = make_test_settings()
    service = GameMasterService(mock_provider, settings)

    with patch.object(mock_provider, "generate_text", side_effect=ProviderError("LLM down")):
        with pytest.raises(ProviderError):
            await service.generate_narration(
                world_state=None,
                recent_events="",
                player_action="I run.",
            )


@pytest.mark.asyncio
async def test_provider_error_propagates_from_generate_event(
    mock_provider: MockProvider,
) -> None:
    settings = make_test_settings()
    service = GameMasterService(mock_provider, settings)

    with patch.object(mock_provider, "generate_text", side_effect=ProviderError("LLM down")):
        with pytest.raises(ProviderError):
            await service.generate_event(
                world_state=None,
                event_seed="test",
                event_type="ambush",
                urgency="immediate",
                player_actions="walking",
            )
