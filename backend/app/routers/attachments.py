import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.attachment import (
    AttachmentUploadRequest,
    AttachmentUploadResponse,
)
from app.services.attachment_service import upload_attachment
from app.services.storage_service import ObjectStorageService

router = APIRouter()
logger = structlog.get_logger()


def get_storage_service() -> ObjectStorageService:
    """Get the object storage service instance."""
    return ObjectStorageService(settings)


@router.post("/attachments/upload", response_model=AttachmentUploadResponse, status_code=201)
@limiter.limit(settings.rate_limit_creates)
async def upload_attachment_endpoint(
    request: Request,
    attachment_data: AttachmentUploadRequest,
    db: Session = Depends(get_db),
    storage_service: ObjectStorageService = Depends(get_storage_service),
):
    """
    Upload an encrypted file attachment to object storage.

    The attachment is created without being linked to a secret.
    It will be linked when the secret is created via POST /secrets.

    Returns the storage_key and attachment_id for later reference.
    """
    if not settings.object_storage_enabled:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not enabled",
        )

    # Validate file size
    import base64

    blob_size = len(base64.b64decode(attachment_data.encrypted_blob))
    max_size = settings.max_attachment_size_bytes
    if blob_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"Attachment size {blob_size} exceeds limit of {max_size} bytes",
        )

    try:
        attachment = await upload_attachment(
            db,
            storage_service,
            encrypted_blob_b64=attachment_data.encrypted_blob,
            blob_iv_b64=attachment_data.blob_iv,
            blob_auth_tag_b64=attachment_data.blob_auth_tag,
            encrypted_metadata_b64=attachment_data.encrypted_metadata,
            metadata_iv_b64=attachment_data.metadata_iv,
            metadata_auth_tag_b64=attachment_data.metadata_auth_tag,
            position=attachment_data.position,
        )
    except Exception as e:
        logger.error("attachment_upload_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to upload attachment")

    logger.info(
        "attachment_uploaded",
        attachment_id=attachment.id,
        storage_key_prefix=attachment.storage_key[:20],
        blob_size=attachment.blob_size,
    )

    return AttachmentUploadResponse(
        storage_key=attachment.storage_key,
        attachment_id=attachment.id,
    )
