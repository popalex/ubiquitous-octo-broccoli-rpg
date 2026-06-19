"""Convert all entity IDs from UUID to ULID (clean cut)

Rewrites every primary key and foreign key from a 36-char UUID to a canonical
26-char ULID, then tightens the columns to ``VARCHAR(26)`` and adds a CHECK that
every id is a well-formed ULID. After this migration no UUIDs remain.

New ULIDs are derived from each row's ``created_at`` so they stay sortable in
creation order (the random component keeps same-millisecond rows distinct).

The old<->new mapping is recorded in the ``id_ulid_remap`` audit table, which is
kept after upgrade so ``downgrade`` can restore the original UUIDs exactly.
**Take a `pg_dump` backup before running** (see ulid-migration.md runbook) — this
rewrites live data.

Revision ID: e7d1c9b2a3f4
Revises: c3d4e5f6a7b8
Create Date: 2026-06-19 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e7d1c9b2a3f4'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of the ULID shape (migrations must not import app code that drifts).
ULID_REGEX = "^[0-7][0-9A-HJKMNP-TV-Z]{25}$"

# Every table whose primary key is an entity id.
PK_TABLES = [
    "character_cards",
    "world_states",
    "sessions",
    "turns",
    "memory_facts",
    "episode_summaries",
    "quests",
    "relationship_states",
    "world_state_ledger",
]

# Foreign keys carrying entity ids, captured from the live catalog:
# (constraint_name, child_table, fk_column, parent_table, ondelete)
FKS = [
    ("episode_summaries_session_id_fkey", "episode_summaries", "session_id", "sessions", "CASCADE"),
    ("memory_facts_character_card_id_fkey", "memory_facts", "character_card_id", "character_cards", "SET NULL"),
    ("memory_facts_session_id_fkey", "memory_facts", "session_id", "sessions", "CASCADE"),
    ("memory_facts_source_turn_id_fkey", "memory_facts", "source_turn_id", "turns", "SET NULL"),
    ("quests_session_id_fkey", "quests", "session_id", "sessions", "CASCADE"),
    ("quests_source_turn_id_fkey", "quests", "source_turn_id", "turns", "SET NULL"),
    ("relationship_states_last_observed_turn_id_fkey", "relationship_states", "last_observed_turn_id", "turns", "SET NULL"),  # noqa: E501
    ("relationship_states_session_id_fkey", "relationship_states", "session_id", "sessions", "CASCADE"),
    ("fk_sessions_parent_session_id", "sessions", "parent_session_id", "sessions", "SET NULL"),
    ("sessions_character_card_id_fkey", "sessions", "character_card_id", "character_cards", "CASCADE"),
    ("sessions_world_state_id_fkey", "sessions", "world_state_id", "world_states", "SET NULL"),
    ("turns_session_id_fkey", "turns", "session_id", "sessions", "CASCADE"),
    ("world_state_ledger_session_id_fkey", "world_state_ledger", "session_id", "sessions", "CASCADE"),
    ("world_state_ledger_turn_id_fkey", "world_state_ledger", "turn_id", "turns", "SET NULL"),
]

# Every id-bearing column (PK + FK), for the width change.
ALL_ID_COLUMNS = [(t, "id") for t in PK_TABLES] + [(child, col) for _, child, col, _, _ in FKS]


def upgrade() -> None:
    from ulid import ULID

    bind = op.get_bind()

    # 1. Audit table: the old<->new mapping, kept as the backup-of-record and the
    #    join source for the set-based rewrites below.
    op.create_table(
        "id_ulid_remap",
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("old_id", sa.String(36), nullable=False),
        sa.Column("new_id", sa.String(26), nullable=False),
    )
    op.create_index("ix_id_ulid_remap_old_id", "id_ulid_remap", ["old_id"], unique=True)

    # 2. Generate a ULID per row from its created_at, recording the mapping.
    for table in PK_TABLES:
        rows = bind.execute(sa.text(f"SELECT id, created_at FROM {table}")).fetchall()
        for old_id, created_at in rows:
            new_id = str(ULID.from_datetime(created_at)) if created_at is not None else str(ULID())
            bind.execute(
                sa.text("INSERT INTO id_ulid_remap (table_name, old_id, new_id) VALUES (:t, :o, :n)"),
                {"t": table, "o": old_id, "n": new_id},
            )

    # 3. Drop FK constraints so referenced primary keys can be rewritten.
    for name, child, _col, _parent, _ondelete in FKS:
        op.drop_constraint(name, child, type_="foreignkey")

    # 4. Rewrite primary keys, then foreign keys, via the audit-table join.
    for table in PK_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} t SET id = m.new_id "
                f"FROM id_ulid_remap m WHERE m.table_name = '{table}' AND m.old_id = t.id"
            )
        )
    for _name, child, col, parent, _ondelete in FKS:
        op.execute(
            sa.text(
                f"UPDATE {child} c SET {col} = m.new_id "
                f"FROM id_ulid_remap m WHERE m.table_name = '{parent}' AND m.old_id = c.{col}"
            )
        )

    # 5. Recreate the FK constraints.
    for name, child, col, parent, ondelete in FKS:
        op.create_foreign_key(name, child, parent, [col], ["id"], ondelete=ondelete)

    # 6. Tighten the columns to ULID width and add the CHECK guard.
    for table, col in ALL_ID_COLUMNS:
        op.alter_column(table, col, type_=sa.String(26), existing_type=sa.String(36))
    for table in PK_TABLES:
        op.create_check_constraint(f"ck_{table}_id_ulid", table, f"id ~ '{ULID_REGEX}'")


def downgrade() -> None:
    # Reverse of upgrade, restoring the original UUIDs from the audit table.
    for table in PK_TABLES:
        op.drop_constraint(f"ck_{table}_id_ulid", table, type_="check")
    for table, col in ALL_ID_COLUMNS:
        op.alter_column(table, col, type_=sa.String(36), existing_type=sa.String(26))
    for name, child, _col, _parent, _ondelete in FKS:
        op.drop_constraint(name, child, type_="foreignkey")

    for table in PK_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} t SET id = m.old_id "
                f"FROM id_ulid_remap m WHERE m.table_name = '{table}' AND m.new_id = t.id"
            )
        )
    for _name, child, col, parent, _ondelete in FKS:
        op.execute(
            sa.text(
                f"UPDATE {child} c SET {col} = m.old_id "
                f"FROM id_ulid_remap m WHERE m.table_name = '{parent}' AND m.new_id = c.{col}"
            )
        )

    for name, child, col, parent, ondelete in FKS:
        op.create_foreign_key(name, child, parent, [col], ["id"], ondelete=ondelete)

    op.drop_index("ix_id_ulid_remap_old_id", table_name="id_ulid_remap")
    op.drop_table("id_ulid_remap")
