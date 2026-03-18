"""Use native UUID column type

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-17

Migrate UUID primary-key and foreign-key columns from String(36) to the
native Uuid type.  On PostgreSQL this changes the physical column type to
`uuid`; on SQLite both types store as TEXT so the migration is a no-op.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) pairs to migrate from String(36) -> Uuid
_UUID_COLUMNS: list[tuple[str, str]] = [
    ("secrets", "id"),
    ("pow_challenges", "id"),
    ("capability_tokens", "id"),
    ("capability_tokens", "consumed_by_secret_id"),
    ("secret_attachments", "id"),
    ("secret_attachments", "secret_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite stores both String and Uuid as TEXT — nothing to do.
        return

    # PostgreSQL: alter column types to native uuid
    for table, column in _UUID_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Uuid(as_uuid=True),
            existing_type=sa.String(36),
            postgresql_using=f"{column}::uuid",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    # PostgreSQL: revert to String(36)
    for table, column in _UUID_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(36),
            existing_type=sa.Uuid(as_uuid=True),
            postgresql_using=f"{column}::text",
        )
