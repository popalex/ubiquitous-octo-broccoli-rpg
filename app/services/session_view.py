"""Serializers: ``Session`` ORM row → API response schema.

The ~18-field session→response mapping (resolved feature flags, character/world
names, fork lineage) was hand-inlined in four routes (`/session/init`,
`/sessions`, `/session/{id}`, fork); adding one field meant editing all four.
These helpers single-source that mapping. The pure ``session_to_*`` functions
take an already-loaded session (relationships eager-loaded where names are
needed); ``list_sessions_with_summaries`` also owns the list query + per-session
summary fetch.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.models import CharacterSheet, EpisodeSummary, Turn
from app.models import Session as ChatSession
from app.schemas import CharacterSheetResponse, SessionDetailResponse, SessionInitResponse, SessionListItem
from app.services.character_sheet import CharacterSheetService
from app.services.features import character_sheet_on, dice_on, quests_on, world_state_on

_SUMMARY_PREVIEW_CHARS = 200


def sheet_to_response(sheet: CharacterSheet | None, settings: Settings) -> CharacterSheetResponse | None:
    """Serialize a character sheet, deriving ``xp_to_next`` from the level curve."""
    if sheet is None:
        return None
    service = CharacterSheetService(settings)
    return CharacterSheetResponse(
        might=sheet.might,
        finesse=sheet.finesse,
        wits=sheet.wits,
        presence=sheet.presence,
        level=sheet.level,
        xp=sheet.xp,
        xp_to_next=service.xp_to_next(sheet.xp),
        xp_for_level=service.xp_for_level(),
    )


def session_to_init(
    session: ChatSession, settings: Settings, sheet: CharacterSheet | None = None
) -> SessionInitResponse:
    """Response for a freshly created session (no character/world names, no
    status/lineage — those aren't part of the init view)."""
    return SessionInitResponse(
        session_id=session.id,
        character_card_id=session.character_card_id,
        world_state_id=session.world_state_id,
        title=session.title,
        turn_count=session.turn_count,
        gm_enabled=session.gm_enabled,
        suggestions_enabled=session.suggestions_enabled,
        current_location=session.current_location,
        time_of_day=session.time_of_day,
        world_state_enabled=world_state_on(session, settings),
        quests_enabled=quests_on(session, settings),
        dice_enabled=dice_on(session, settings),
        character_sheet_enabled=character_sheet_on(session, settings),
        sheet=sheet_to_response(sheet, settings),
    )


def session_to_detail(
    session: ChatSession, settings: Settings, sheet: CharacterSheet | None = None
) -> SessionDetailResponse:
    """Full session view. ``character_card`` / ``world_state`` must be loaded."""
    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        status=session.status,
        gm_enabled=session.gm_enabled,
        suggestions_enabled=session.suggestions_enabled,
        turn_count=session.turn_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        character_card_id=session.character_card_id,
        world_state_id=session.world_state_id,
        character_name=session.character_card.name if session.character_card else None,
        world_name=session.world_state.name if session.world_state else None,
        current_location=session.current_location,
        time_of_day=session.time_of_day,
        world_state_enabled=world_state_on(session, settings),
        quests_enabled=quests_on(session, settings),
        dice_enabled=dice_on(session, settings),
        character_sheet_enabled=character_sheet_on(session, settings),
        sheet=sheet_to_response(sheet, settings),
        parent_session_id=session.parent_session_id,
        forked_at_turn=session.forked_at_turn,
    )


def session_to_list_item(session: ChatSession, settings: Settings, summary: str | None) -> SessionListItem:
    """List-row view. ``character_card`` / ``world_state`` must be loaded; the
    per-session ``summary`` preview is supplied by the caller."""
    return SessionListItem(
        id=session.id,
        title=session.title,
        status=session.status,
        gm_enabled=session.gm_enabled,
        suggestions_enabled=session.suggestions_enabled,
        turn_count=session.turn_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        character_card_id=session.character_card_id,
        world_state_id=session.world_state_id,
        character_name=session.character_card.name if session.character_card else None,
        world_name=session.world_state.name if session.world_state else None,
        summary=summary,
        world_state_enabled=world_state_on(session, settings),
        quests_enabled=quests_on(session, settings),
        dice_enabled=dice_on(session, settings),
        character_sheet_enabled=character_sheet_on(session, settings),
        parent_session_id=session.parent_session_id,
        forked_at_turn=session.forked_at_turn,
    )


async def _latest_summary(db: AsyncSession, session_id: str) -> str | None:
    """Preview text for a list row: the latest episode summary, falling back to
    the latest assistant turn, truncated to a preview length."""
    summary = await db.scalar(
        select(EpisodeSummary)
        .where(EpisodeSummary.session_id == session_id)
        .order_by(EpisodeSummary.created_at.desc())
        .limit(1)
    )
    if summary:
        return summary.content[:_SUMMARY_PREVIEW_CHARS]
    last_turn = await db.scalar(
        select(Turn)
        .where(Turn.session_id == session_id, Turn.role == "assistant")
        .order_by(Turn.turn_index.desc())
        .limit(1)
    )
    return last_turn.content[:_SUMMARY_PREVIEW_CHARS] if last_turn else None


async def list_sessions_with_summaries(db: AsyncSession, settings: Settings) -> list[SessionListItem]:
    """Load all non-archived sessions (newest first) with character/world names
    and a summary preview, serialized to list items."""
    sessions = (
        await db.scalars(
            select(ChatSession)
            .where(ChatSession.status != "archived")
            .options(joinedload(ChatSession.character_card), joinedload(ChatSession.world_state))
            .order_by(ChatSession.updated_at.desc())
        )
    ).all()
    return [session_to_list_item(s, settings, await _latest_summary(db, s.id)) for s in sessions]
