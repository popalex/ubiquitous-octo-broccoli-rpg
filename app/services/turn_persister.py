"""Turn persistence for chat / GM exchanges.

Both the stream and non-stream entry points create the same user + assistant
``Turn`` rows (plus an optional pre-narration GM turn), bump
``session.turn_count``, commit, and refresh — four near-identical blocks. This
single-sources the turn indices, ``turn_type``, token estimates, and the
commit/refresh so they can't drift.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as ChatSession
from app.models import Turn


class TurnPersister:
    def __init__(self, estimate_tokens: Callable[[str], int]) -> None:
        self._estimate_tokens = estimate_tokens

    async def persist_chat_turns(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        assistant_content: str,
        continuity_notes: str | None = None,
    ) -> Turn:
        """Create the user + assistant turns for a plain chat exchange, bump
        ``turn_count``, commit, and refresh. Returns the assistant ``Turn`` (its
        id seeds post-turn work; the stream path also writes its retcon note)."""
        next_user_index = session.turn_count + 1
        next_actor_index = session.turn_count + 2
        assistant_turn = Turn(
            session_id=session.id,
            turn_index=next_actor_index,
            role="assistant",
            content=assistant_content,
            token_estimate=self._estimate_tokens(assistant_content),
            continuity_notes=continuity_notes,
        )
        db.add_all(
            [
                Turn(
                    session_id=session.id,
                    turn_index=next_user_index,
                    role="user",
                    content=user_message,
                    token_estimate=self._estimate_tokens(user_message),
                ),
                assistant_turn,
            ]
        )
        session.turn_count = next_actor_index
        await db.commit()
        await db.refresh(session)
        return assistant_turn

    async def persist_gm_turns(
        self,
        db: AsyncSession,
        session: ChatSession,
        *,
        user_message: str,
        assistant_content: str,
        pre_narration: str | None = None,
        post_narration: str | None = None,
        continuity_notes: str | None = None,
    ) -> Turn:
        """Create an optional pre-narration GM turn + the user + assistant turns
        for a GM exchange, bump ``turn_count``, commit, and refresh. Any
        ``post_narration`` is appended to the assistant content. Returns the
        assistant ``Turn``."""
        turns_to_add: list[Turn] = []
        current_index = session.turn_count

        # Store pre-narration as a separate GM turn (kept for memory extraction).
        if pre_narration:
            current_index += 1
            turns_to_add.append(
                Turn(
                    session_id=session.id,
                    turn_index=current_index,
                    role="assistant",
                    content=f"[Scene Narration]\n{pre_narration}",
                    token_estimate=self._estimate_tokens(pre_narration),
                    turn_type="gm_narration",
                )
            )

        current_index += 1
        turns_to_add.append(
            Turn(
                session_id=session.id,
                turn_index=current_index,
                role="user",
                content=user_message,
                token_estimate=self._estimate_tokens(user_message),
            )
        )

        full_assistant_content = assistant_content
        if post_narration:
            full_assistant_content = f"{assistant_content}\n\n---\n\n{post_narration}"

        current_index += 1
        assistant_turn = Turn(
            session_id=session.id,
            turn_index=current_index,
            role="assistant",
            content=full_assistant_content,
            token_estimate=self._estimate_tokens(full_assistant_content),
            continuity_notes=continuity_notes,
        )
        turns_to_add.append(assistant_turn)

        db.add_all(turns_to_add)
        session.turn_count = current_index
        await db.commit()
        await db.refresh(session)
        return assistant_turn
