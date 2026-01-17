"""Add secret_attachments table

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-17

Adds secret_attachments table for tracking encrypted file attachments
stored in object storage (S3/MinIO).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secret_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "secret_id",
            sa.String(36),
            sa.ForeignKey("secrets.id", ondelete="CASCADE"),
            nullable=True,  # Nullable to allow orphaned uploads during upload→create flow
        ),
        # Object storage location
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        # Encrypted metadata (filename, mime_type as JSON)
        sa.Column("encrypted_metadata", sa.LargeBinary, nullable=False),
        sa.Column("metadata_iv", sa.LargeBinary(12), nullable=False),
        sa.Column("metadata_auth_tag", sa.LargeBinary(16), nullable=False),
        # Blob encryption params
        sa.Column("blob_iv", sa.LargeBinary(12), nullable=False),
        sa.Column("blob_auth_tag", sa.LargeBinary(16), nullable=False),
        sa.Column("blob_size", sa.Integer, nullable=False),
        # Ordering
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        # Timestamps
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # Indexes
    op.create_index("ix_secret_attachments_secret_id", "secret_attachments", ["secret_id"])


def downgrade() -> None:
    op.drop_index("ix_secret_attachments_secret_id", table_name="secret_attachments")
    op.drop_table("secret_attachments")
