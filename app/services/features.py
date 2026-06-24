"""Per-session feature-flag resolution.

``world_state_enabled`` and ``quests_enabled`` exist both as global Settings
flags and as nullable per-session overrides chosen at chronicle creation.
A session value of ``NULL`` inherits the global; anything else wins.
"""

from __future__ import annotations

from app.config import Settings
from app.models import Session as ChatSession


def world_state_on(session: ChatSession, settings: Settings) -> bool:
    if session.world_state_enabled is not None:
        return session.world_state_enabled
    return settings.world_state_enabled


def quests_on(session: ChatSession, settings: Settings) -> bool:
    if session.quests_enabled is not None:
        return session.quests_enabled
    return settings.quests_enabled


def dice_on(session: ChatSession, settings: Settings) -> bool:
    if session.dice_enabled is not None:
        return session.dice_enabled
    return settings.dice_enabled


def character_sheet_on(session: ChatSession, settings: Settings) -> bool:
    if session.character_sheet_enabled is not None:
        return session.character_sheet_enabled
    return settings.character_sheet_enabled
