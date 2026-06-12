"""
Game Master Service

Handles narration, event generation, NPC orchestration, and story progression.
Acts as the world's voice, separate from individual character actors.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Session as ChatSession
from app.models import Turn, WorldState
from app.prompts import (
    GM_EVENT_CHECK_PROMPT,
    GM_EVENT_GENERATE_PROMPT,
    GM_NARRATION_PROMPT,
    GM_NPC_DIALOGUE_PROMPT,
    GM_SCENE_TRANSITION_PROMPT,
    GM_SYSTEM_PROMPT,
    GM_WORLD_STATE_UPDATE_PROMPT,
)
from app.providers.base import BaseModelProvider, ProviderError, ProviderMessage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EventCheckResult:
    """Result of checking whether an event should trigger."""

    should_trigger: bool
    event_type: str
    event_seed: str
    urgency: str
    reasoning: str


@dataclass(slots=True)
class GeneratedEvent:
    """A fully generated event with narrative content."""

    event_type: str
    urgency: str
    description: str
    npcs_involved: list[str] = field(default_factory=list)
    raw_response: str = ""


@dataclass(slots=True)
class SceneTransition:
    """Result of a scene transition."""

    narration: str
    time_passed: str
    new_scene_elements: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorldStateUpdate:
    """Changes to the canonical world state."""

    entity: str
    change_type: str
    old_value: str | None
    new_value: str
    permanence: str


@dataclass(slots=True)
class WorldStateUpdateResult:
    """Full result of world state analysis."""

    updates: list[WorldStateUpdate] = field(default_factory=list)
    flags_set: list[str] = field(default_factory=list)
    flags_cleared: list[str] = field(default_factory=list)


class GameMasterService:
    """
    Coordinates world-level narrative generation.

    Responsibilities:
    - Scene narration and atmosphere
    - Event generation and triggering
    - NPC dialogue (non-player characters)
    - Scene transitions
    - World state updates
    """

    def __init__(
        self,
        gm_provider: BaseModelProvider,
        settings: Settings | None = None,
    ) -> None:
        self.gm_provider = gm_provider
        self.settings = settings or get_settings()

    def _build_gm_system_prompt(
        self,
        world_state: WorldState | None,
        active_characters: list[str] | None = None,
        scene_context: str = "",
    ) -> str:
        """Build the GM system prompt with world context."""
        if world_state is None:
            return GM_SYSTEM_PROMPT.format(
                world_name="Unknown World",
                world_description="A mysterious realm.",
                world_canon="",
                hard_rules="None specified.",
                active_characters="None specified.",
                scene_context=scene_context or "Scene not established.",
            )

        return GM_SYSTEM_PROMPT.format(
            world_name=world_state.name,
            world_description=world_state.description,
            world_canon=world_state.canon,
            hard_rules=world_state.hard_rules,
            active_characters=", ".join(active_characters) if active_characters else "None specified.",
            scene_context=scene_context or "Scene not established.",
        )

    async def generate_narration(
        self,
        world_state: WorldState | None,
        recent_events: str,
        player_action: str,
        scene_context: str = "",
    ) -> str:
        """
        Generate atmospheric scene narration.

        Args:
            world_state: Current world configuration
            recent_events: Summary of recent happenings
            player_action: The player's last action
            scene_context: Current scene description

        Returns:
            Narrative text describing the scene
        """
        system_prompt = self._build_gm_system_prompt(world_state, scene_context=scene_context)
        user_prompt = GM_NARRATION_PROMPT.format(
            recent_events=recent_events,
            player_action=player_action,
        )

        narration = await self.gm_provider.generate_text(
            [
                ProviderMessage(role="system", content=system_prompt),
                ProviderMessage(role="user", content=user_prompt),
            ],
            temperature=self.settings.gm_temperature,
            max_tokens=self.settings.gm_narration_max_tokens,
        )
        return narration.strip()

    async def generate_narration_stream(
        self,
        world_state: WorldState | None,
        recent_events: str,
        player_action: str,
        scene_context: str = "",
    ) -> AsyncIterator[str]:
        """Stream narration generation for real-time UI."""
        system_prompt = self._build_gm_system_prompt(world_state, scene_context=scene_context)
        user_prompt = GM_NARRATION_PROMPT.format(
            recent_events=recent_events,
            player_action=player_action,
        )

        async for chunk in self.gm_provider.generate_text_stream(
            [
                ProviderMessage(role="system", content=system_prompt),
                ProviderMessage(role="user", content=user_prompt),
            ],
            temperature=self.settings.gm_temperature,
            max_tokens=self.settings.gm_narration_max_tokens,
        ):
            yield chunk

    async def check_for_event(
        self,
        db: AsyncSession,
        session: ChatSession,
        location: str = "unknown",
        time_of_day: str = "unknown",
        quest_pressure: str = "",
    ) -> EventCheckResult:
        """
        Determine if an event should trigger based on game state.

        Uses both probabilistic checks and LLM analysis to decide
        whether the current moment warrants an event. When neglected quests
        are supplied via ``quest_pressure``, the probabilistic gate is skipped
        so the LLM reliably gets the chance to move the world on them.
        """
        # Early exit based on interval
        if session.turn_count % self.settings.event_check_interval != 0:
            return EventCheckResult(
                should_trigger=False,
                event_type="none",
                event_seed="",
                urgency="",
                reasoning="Not at event check interval.",
            )

        # Probabilistic gate
        if not quest_pressure and random.random() > self.settings.event_probability:
            return EventCheckResult(
                should_trigger=False,
                event_type="none",
                event_seed="",
                urgency="",
                reasoning="Random check did not trigger.",
            )

        # Get recent transcript for context
        recent_turns = (
            await db.scalars(
                select(Turn).where(Turn.session_id == session.id).order_by(Turn.turn_index.desc()).limit(6)
            )
        ).all()
        recent_transcript = "\n".join(f"{turn.role.upper()}: {turn.content}" for turn in reversed(recent_turns))

        prompt = GM_EVENT_CHECK_PROMPT.format(
            recent_transcript=recent_transcript,
            location=location,
            time_of_day=time_of_day,
            turn_count=session.turn_count,
            quest_pressure=quest_pressure or "None.",
        )

        try:
            result = await self.gm_provider.generate_json(
                [ProviderMessage(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=300,
            )
        except ProviderError as exc:
            logger.exception("Event check failed for session=%s", session.id)
            return EventCheckResult(
                should_trigger=False,
                event_type="none",
                event_seed="",
                urgency="",
                reasoning=f"Provider error: {exc}",
            )

        return EventCheckResult(
            should_trigger=bool(result.get("should_trigger", False)),
            event_type=str(result.get("event_type", "none")),
            event_seed=str(result.get("event_seed", "")),
            urgency=str(result.get("urgency", "gradual")),
            reasoning=str(result.get("reasoning", "")),
        )

    async def generate_event(
        self,
        world_state: WorldState | None,
        event_seed: str,
        event_type: str,
        urgency: str,
        player_actions: str,
        quest_context: str = "",
    ) -> GeneratedEvent:
        """
        Generate a full event narrative from a seed.

        Args:
            world_state: Current world configuration
            event_seed: Brief concept for the event
            event_type: Category of event
            urgency: immediate/gradual/background
            player_actions: Recent player actions for context

        Returns:
            Fully realized event with narrative
        """
        world_context = ""
        if world_state:
            world_context = f"World: {world_state.name}\n{world_state.description}\nCanon: {world_state.canon}"

        prompt = GM_EVENT_GENERATE_PROMPT.format(
            event_seed=event_seed,
            event_type=event_type,
            urgency=urgency,
            world_context=world_context,
            quest_context=quest_context or "None.",
            player_actions=player_actions,
        )

        system_prompt = self._build_gm_system_prompt(world_state)

        description = await self.gm_provider.generate_text(
            [
                ProviderMessage(role="system", content=system_prompt),
                ProviderMessage(role="user", content=prompt),
            ],
            temperature=self.settings.gm_temperature,
            max_tokens=self.settings.gm_max_output_tokens,
        )

        return GeneratedEvent(
            event_type=event_type,
            urgency=urgency,
            description=description.strip(),
            raw_response=description,
        )

    async def generate_scene_transition(
        self,
        world_state: WorldState | None,
        previous_scene: str,
        transition_type: str,
        destination: str,
    ) -> SceneTransition:
        """
        Generate narrative for transitioning between scenes.

        Args:
            world_state: Current world configuration
            previous_scene: Description of scene being left
            transition_type: Type of transition (travel, teleport, time_skip, etc.)
            destination: Where the player is going

        Returns:
            Transition narration and metadata
        """
        prompt = GM_SCENE_TRANSITION_PROMPT.format(
            previous_scene=previous_scene,
            transition_type=transition_type,
            destination=destination,
        )

        try:
            result = await self.gm_provider.generate_json(
                [ProviderMessage(role="user", content=prompt)],
                temperature=self.settings.gm_temperature,
                max_tokens=400,
            )
        except ProviderError:
            logger.exception("Scene transition generation failed")
            return SceneTransition(
                narration=f"You arrive at {destination}.",
                time_passed="some time",
                new_scene_elements=[],
            )

        return SceneTransition(
            narration=str(result.get("narration", f"You arrive at {destination}.")),
            time_passed=str(result.get("time_passed", "some time")),
            new_scene_elements=list(result.get("new_scene_elements", [])),
        )

    async def generate_npc_dialogue(
        self,
        world_state: WorldState | None,
        npc_name: str,
        npc_description: str,
        npc_disposition: str,
        npc_goal: str,
        conversation_context: str,
        player_statement: str,
    ) -> str:
        """
        Generate dialogue for a specific NPC.

        This allows the GM to voice NPCs distinct from the main character.
        """
        system_prompt = self._build_gm_system_prompt(world_state)
        prompt = GM_NPC_DIALOGUE_PROMPT.format(
            npc_name=npc_name,
            npc_description=npc_description,
            npc_disposition=npc_disposition,
            npc_goal=npc_goal,
            conversation_context=conversation_context,
            player_statement=player_statement,
        )

        dialogue = await self.gm_provider.generate_text(
            [
                ProviderMessage(role="system", content=system_prompt),
                ProviderMessage(role="user", content=prompt),
            ],
            temperature=self.settings.gm_temperature,
            max_tokens=self.settings.gm_max_output_tokens,
        )
        return dialogue.strip()

    async def analyze_world_state_changes(
        self,
        events_summary: str,
        current_state: str,
    ) -> WorldStateUpdateResult:
        """
        Analyze recent events and determine canonical world state changes.

        This is used to update persistent world state based on what
        happened in the narrative.
        """
        prompt = GM_WORLD_STATE_UPDATE_PROMPT.format(
            events_summary=events_summary,
            current_state=current_state,
        )

        try:
            result = await self.gm_provider.generate_json(
                [ProviderMessage(role="user", content=prompt)],
                temperature=0.1,  # Low temperature for deterministic updates
                max_tokens=500,
            )
        except ProviderError:
            logger.exception("World state analysis failed")
            return WorldStateUpdateResult()

        updates = []
        for update_data in result.get("updates", []):
            updates.append(
                WorldStateUpdate(
                    entity=str(update_data.get("entity", "")),
                    change_type=str(update_data.get("change_type", "modified")),
                    old_value=update_data.get("old_value"),
                    new_value=str(update_data.get("new_value", "")),
                    permanence=str(update_data.get("permanence", "permanent")),
                )
            )

        return WorldStateUpdateResult(
            updates=updates,
            flags_set=list(result.get("flags_set", [])),
            flags_cleared=list(result.get("flags_cleared", [])),
        )


def build_game_master_service(settings: Settings | None = None) -> GameMasterService:
    """Factory function to create a GameMasterService with configured provider."""
    from app.providers.base import build_provider

    resolved_settings = settings or get_settings()
    gm_provider = build_provider(
        resolved_settings.gm_provider,
        resolved_settings.gm_model_name,
        resolved_settings,
    )
    return GameMasterService(gm_provider, resolved_settings)
