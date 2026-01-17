import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.secret_attachment import SecretAttachment


class Secret(Base):
    __tablename__ = "secrets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Token prefixes for O(1) lookup (first 16 hex chars of token)
    # These are indexed and used to narrow down candidates before Argon2 verification
    edit_token_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    decrypt_token_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)

    # Full Argon2 hashes for secure verification after prefix lookup
    edit_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    decrypt_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    # Encrypted payload (nullable for cleared secrets)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    iv: Mapped[bytes | None] = mapped_column(LargeBinary(12), nullable=True)
    auth_tag: Mapped[bytes | None] = mapped_column(LargeBinary(16), nullable=True)

    # Timing (stored as naive datetimes in UTC, serialized with Z suffix)
    unlock_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    # Metadata
    ciphertext_size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    attachments: Mapped[list["SecretAttachment"]] = relationship(
        "SecretAttachment",
        back_populates="secret",
        cascade="all, delete-orphan",
        order_by="SecretAttachment.position",
    )
