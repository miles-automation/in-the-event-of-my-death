import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.secret import Secret


class SecretAttachment(Base):
    """
    Tracks encrypted file attachments stored in object storage.

    Each attachment belongs to a Secret and stores:
    - storage_key: S3/MinIO object key for the encrypted blob
    - encrypted_metadata: AES-256-GCM encrypted JSON with filename/mime_type
    - blob encryption params: IV and auth tag for the stored blob
    - position: ordering for multiple attachments
    """

    __tablename__ = "secret_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    secret_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("secrets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Object storage location
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)

    # Encrypted metadata (filename, mime_type as JSON, encrypted client-side)
    encrypted_metadata: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_iv: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    metadata_auth_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)

    # Blob encryption params (for the object storage blob)
    blob_iv: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    blob_auth_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    blob_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Ordering for multiple attachments
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Relationship back to Secret
    secret: Mapped["Secret"] = relationship("Secret", back_populates="attachments")
