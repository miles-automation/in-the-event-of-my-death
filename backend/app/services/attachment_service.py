import base64
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.secret import Secret
from app.models.secret_attachment import SecretAttachment
from app.services.storage_service import ObjectStorageService


async def upload_attachment(
    db: Session,
    storage_service: ObjectStorageService,
    *,
    encrypted_blob_b64: str,
    blob_iv_b64: str,
    blob_auth_tag_b64: str,
    encrypted_metadata_b64: str,
    metadata_iv_b64: str,
    metadata_auth_tag_b64: str,
    position: int = 0,
) -> SecretAttachment:
    """
    Upload an encrypted file attachment to object storage and create a DB record.

    The attachment is created without a secret_id initially (orphaned).
    It will be linked to a secret when the secret is created.

    Args:
        db: Database session
        storage_service: Object storage service instance
        encrypted_blob_b64: Base64 encoded encrypted file bytes
        blob_iv_b64: Base64 encoded 12-byte IV for blob encryption
        blob_auth_tag_b64: Base64 encoded 16-byte auth tag for blob
        encrypted_metadata_b64: Base64 encoded encrypted metadata JSON
        metadata_iv_b64: Base64 encoded 12-byte IV for metadata encryption
        metadata_auth_tag_b64: Base64 encoded 16-byte auth tag for metadata
        position: Ordering index for multiple attachments

    Returns:
        The created SecretAttachment record
    """
    # Decode base64 inputs
    encrypted_blob = base64.b64decode(encrypted_blob_b64)
    blob_iv = base64.b64decode(blob_iv_b64)
    blob_auth_tag = base64.b64decode(blob_auth_tag_b64)
    encrypted_metadata = base64.b64decode(encrypted_metadata_b64)
    metadata_iv = base64.b64decode(metadata_iv_b64)
    metadata_auth_tag = base64.b64decode(metadata_auth_tag_b64)

    # Generate unique storage key
    storage_key = f"attachments/{uuid.uuid4()}"

    # Upload to S3
    await storage_service.upload_bytes(
        object_key=storage_key,
        data=encrypted_blob,
        content_type="application/octet-stream",
    )

    # Create DB record (orphaned - no secret_id yet)
    attachment = SecretAttachment(
        storage_key=storage_key,
        encrypted_metadata=encrypted_metadata,
        metadata_iv=metadata_iv,
        metadata_auth_tag=metadata_auth_tag,
        blob_iv=blob_iv,
        blob_auth_tag=blob_auth_tag,
        blob_size=len(encrypted_blob),
        position=position,
        secret_id=None,  # Will be linked when secret is created
    )

    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    return attachment


def link_attachments_to_secret(
    db: Session,
    secret_id: str,
    attachment_ids: list[str],
) -> int:
    """
    Link orphaned attachments to a secret.

    Args:
        db: Database session
        secret_id: The secret ID to link attachments to
        attachment_ids: List of attachment IDs to link

    Returns:
        Number of attachments successfully linked
    """
    if not attachment_ids:
        return 0

    # Update all matching attachments that are still orphaned
    count = (
        db.query(SecretAttachment)
        .filter(
            SecretAttachment.id.in_(attachment_ids),
            SecretAttachment.secret_id == None,  # noqa: E711 - Only link orphaned
        )
        .update({"secret_id": secret_id}, synchronize_session=False)
    )

    db.commit()
    return count


def find_attachment_by_storage_key(
    db: Session,
    storage_key: str,
) -> SecretAttachment | None:
    """
    Find an attachment by its storage key.

    Args:
        db: Database session
        storage_key: The S3 object key

    Returns:
        The attachment if found, None otherwise
    """
    return db.query(SecretAttachment).filter(SecretAttachment.storage_key == storage_key).first()


def get_attachment_with_secret(
    db: Session,
    storage_key: str,
) -> tuple[SecretAttachment, Secret] | None:
    """
    Find an attachment and its associated secret.

    Args:
        db: Database session
        storage_key: The S3 object key

    Returns:
        Tuple of (attachment, secret) if found, None otherwise
    """
    attachment = find_attachment_by_storage_key(db, storage_key)
    if attachment is None:
        return None

    if attachment.secret_id is None:
        return None  # Orphaned attachment

    secret = db.query(Secret).filter(Secret.id == attachment.secret_id).first()
    if secret is None:
        return None

    return (attachment, secret)


def get_orphaned_attachments(
    db: Session,
    max_age_hours: int = 24,
) -> list[SecretAttachment]:
    """
    Get attachments that were uploaded but never linked to a secret.

    These are candidates for cleanup.

    Args:
        db: Database session
        max_age_hours: Only return attachments older than this many hours

    Returns:
        List of orphaned attachments
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=max_age_hours)

    return (
        db.query(SecretAttachment)
        .filter(
            SecretAttachment.secret_id == None,  # noqa: E711 - Orphaned
            SecretAttachment.created_at < cutoff,
        )
        .all()
    )


async def delete_orphaned_attachments(
    db: Session,
    storage_service: ObjectStorageService,
    max_age_hours: int = 24,
) -> int:
    """
    Delete attachments that were uploaded but never linked to a secret.

    Deletes both the S3 blob and the database record.

    Args:
        db: Database session
        storage_service: Object storage service instance
        max_age_hours: Only delete attachments older than this many hours

    Returns:
        Number of attachments deleted
    """
    orphans = get_orphaned_attachments(db, max_age_hours)

    deleted_count = 0
    for attachment in orphans:
        try:
            # Delete from S3
            await storage_service.delete_object(object_key=attachment.storage_key)
            # Delete from DB
            db.delete(attachment)
            deleted_count += 1
        except Exception:
            # Log but continue - we'll retry on next cleanup run
            pass

    db.commit()
    return deleted_count
