from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.models import CharacterCard, is_ulid, new_id
from tests.factories import CharacterCardFactory, SessionFactory, TurnFactory

# ===========================================================================
# new_id() / is_ulid() — pure helpers
# ===========================================================================


def test_new_id_is_a_canonical_ulid() -> None:
    value = new_id()
    assert len(value) == 26
    assert is_ulid(value)
    # Round-trips through the ULID parser (rejects anything malformed).
    assert str(ULID.from_str(value)) == value


def test_new_id_is_unique() -> None:
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_is_ulid_rejects_uuid_and_junk() -> None:
    assert not is_ulid(str(uuid4()))  # legacy 36-char UUID
    assert not is_ulid("")
    assert not is_ulid("not-a-ulid")
    assert not is_ulid("0" * 25)  # too short
    assert not is_ulid("0" * 27)  # too long
    assert not is_ulid("I" * 26)  # I is not in Crockford base32


def test_ulids_sort_by_creation_time() -> None:
    earlier = str(ULID.from_datetime(datetime(2026, 1, 1, tzinfo=UTC)))
    later = str(ULID.from_datetime(datetime(2026, 6, 19, tzinfo=UTC)))
    # Lexicographic order matches chronological order — the reason for ULIDs.
    assert earlier < later


# ===========================================================================
# Model defaults + DB CHECK constraint
# ===========================================================================


@pytest.mark.asyncio
async def test_model_pk_defaults_to_ulid(db_session: AsyncSession) -> None:
    char = CharacterCardFactory()
    await db_session.flush()
    assert is_ulid(char.id)


@pytest.mark.asyncio
async def test_fk_column_also_holds_ulid(db_session: AsyncSession) -> None:
    session = SessionFactory()
    turn = TurnFactory(session=session, turn_index=1)
    await db_session.flush()
    # FK columns inherit the ULID width/type from the referenced PK.
    assert is_ulid(turn.session_id)
    assert turn.session_id == session.id


@pytest.mark.asyncio
async def test_check_constraint_rejects_non_ulid_id(db_session: AsyncSession) -> None:
    bad = CharacterCard(
        id="not-a-ulid-value",
        name="Bad Id Char",
        description="x",
        hard_rules="none",
    )
    db_session.add(bad)
    # 16-char value fits the column but fails the ULID CHECK.
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_check_constraint_rejects_uuid_id(db_session: AsyncSession) -> None:
    # A legacy 36-char UUID is too long for String(26) (DataError) — and would
    # fail the CHECK even if it fit. Either way it cannot be stored.
    bad = CharacterCard(
        id=str(uuid4()),
        name="Uuid Char",
        description="x",
        hard_rules="none",
    )
    db_session.add(bad)
    with pytest.raises((IntegrityError, DataError)):
        await db_session.flush()
