"""Add vaults table

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-01

Adds vaults table for encrypted vault blob storage.
Each vault stores a single encrypted blob containing all vault entries
and the syncToken, keyed by vaultId = SHA-256(vaultKey).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vaults",
        sa.Column("vault_id", sa.String(64), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("etag", sa.String(36), nullable=False),
        sa.Column("sync_token_hash", sa.String(64), nullable=False),
        sa.Column("ciphertext_size", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("vaults")
