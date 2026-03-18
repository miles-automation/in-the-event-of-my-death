import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.database import Base


class CapabilityToken(Base):
    """
    Capability token for premium features.

    Tokens are bearer instruments that grant permission to create secrets
    with premium features (e.g., file uploads, larger sizes). They bypass
    the Proof-of-Work requirement.

    Tokens are:
    - Single-use: marked consumed after use
    - Tier-based: different tiers unlock different features
    - Payment-agnostic: created via webhook or manually, usable anonymously
    """

    __tablename__ = "capability_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Token lookup (same pattern as secrets: prefix + hash)
    token_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    # Tier and limits
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    max_file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    # Consumption tracking
    consumed_by_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Payment tracking (for audit/reconciliation)
    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Flexible metadata for tracking (recipient info, campaign, etc.)
    token_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
