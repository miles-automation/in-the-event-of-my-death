import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Vault(Base):
    __tablename__ = "vaults"

    # vaultId = SHA-256(vaultKey), hex-encoded (64 chars)
    vault_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Encrypted vault blob (all entries + syncToken + metadata)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # ETag for optimistic concurrency (UUID4, regenerated on each write)
    etag: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))

    # SHA-256(syncToken), hex-encoded (64 chars) — never stores raw syncToken
    sync_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Size tracking for abuse prevention
    ciphertext_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
