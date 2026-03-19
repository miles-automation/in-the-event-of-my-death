"""Add updated_at to secrets and capability_tokens

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-19

Add nullable updated_at (DateTime) column to both secrets and
capability_tokens tables for tracking modification timestamps.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("secrets", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column("capability_tokens", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("capability_tokens", "updated_at")
    op.drop_column("secrets", "updated_at")
