from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.attachment import (
    AttachmentUploadRequest,
    AttachmentUploadResponse,
    AttachmentUrlResponse,
)
from app.services.attachment_service import (
    get_attachment_with_secret,
    upload_attachment,
)
from app.services.secret_service import find_secret_by_decrypt_token
from app.services.storage_service import ObjectStorageService

router = APIRouter()
logger = structlog.get_logger()


def get_storage_service() -> ObjectStorageService:
    """Get the object storage service instance."""
    return ObjectStorageService(settings)


def extract_bearer_token(authorization: str = Header(...)) -> str:
    """Extract token from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    return authorization[7:]


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


@router.get(
    "/attachments/{storage_key:path}", response_model=AttachmentUrlResponse, deprecated=True
)
@limiter.limit(settings.rate_limit_retrieves)
async def get_attachment_url(
    request: Request,
    storage_key: str,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    storage_service: ObjectStorageService = Depends(get_storage_service),
):
    """
    Get a presigned URL for downloading an attachment.

    DEPRECATED: Presigned URLs are now included in the /secrets/retrieve response.
    Use those URLs instead of calling this endpoint separately.

    Requires the decrypt token for the secret this attachment belongs to.
    The secret must be unlocked (past unlock_at) and not yet retrieved.

    Returns a presigned URL valid for 5 minutes.
    """
    if not settings.object_storage_enabled:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not enabled",
        )

    decrypt_token = extract_bearer_token(authorization)

    # Find the secret by decrypt token
    secret = find_secret_by_decrypt_token(db, decrypt_token)
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    # Find the attachment and verify it belongs to this secret
    result = get_attachment_with_secret(db, storage_key)
    if result is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    attachment, attachment_secret = result

    # Verify the attachment belongs to the authenticated secret
    if attachment_secret.id != secret.id:
        raise HTTPException(status_code=403, detail="Attachment does not belong to this secret")

    # Check if secret is available for retrieval
    now = datetime.now(UTC).replace(tzinfo=None)

    if secret.retrieved_at is not None:
        raise HTTPException(
            status_code=410,
            detail={"status": "retrieved", "message": "Secret has already been retrieved"},
        )

    if now >= secret.expires_at:
        raise HTTPException(
            status_code=410,
            detail={"status": "expired", "message": "Secret has expired"},
        )

    if now < secret.unlock_at:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "pending",
                "unlock_at": secret.unlock_at.isoformat() + "Z",
                "message": "Secret not yet available",
            },
        )

    # Generate presigned URL
    expires_in = 300  # 5 minutes
    try:
        presigned_url = await storage_service.generate_presigned_url(
            object_key=storage_key,
            expires_in=expires_in,
        )
    except Exception as e:
        logger.error("presigned_url_failed", error=str(e), storage_key_prefix=storage_key[:20])
        raise HTTPException(status_code=500, detail="Failed to generate download URL")

    logger.info(
        "presigned_url_generated",
        attachment_id=attachment.id,
        secret_id=secret.id,
    )

    return AttachmentUrlResponse(
        presigned_url=presigned_url,
        expires_in=expires_in,
    )
