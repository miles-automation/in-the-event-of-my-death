import base64
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.secret import (
    SecretCreate,
    SecretCreateResponse,
    SecretEditRequest,
    SecretEditResponse,
    SecretIdStatusResponse,
    SecretRetrieveResponse,
    SecretStatusResponse,
)
from app.services.attachment_service import link_attachments_to_secret
from app.services.capability_token_service import (
    consume_capability_token,
    find_capability_token,
)
from app.services.pow_service import (
    compute_expected_difficulty,
    compute_payload_hash,
    mark_challenge_used,
    validate_pow,
)
from app.services.secret_service import (
    create_secret,
    find_secret_by_decrypt_token,
    find_secret_by_edit_token,
    find_secret_by_id,
    get_secret_status,
    retrieve_secret,
    update_secret_dates,
)
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


@router.post("/secrets", response_model=SecretCreateResponse, status_code=201)
@limiter.limit(settings.rate_limit_creates)
async def create_new_secret(
    request: Request,
    secret_data: SecretCreate,
    db: Session = Depends(get_db),
    x_capability_token: str | None = Header(None, alias="X-Capability-Token"),
):
    """
    Create a new time-locked secret.

    Requires EITHER:
    - A valid proof-of-work solution bound to the exact payload, OR
    - A valid capability token (X-Capability-Token header)

    Capability tokens allow larger files and bypass PoW.
    """
    capability_token = None
    challenge = None

    # Check for capability token (bypasses PoW)
    if x_capability_token:
        if len(x_capability_token) != 64:
            raise HTTPException(status_code=400, detail="Invalid capability token format")

        capability_token = find_capability_token(db, x_capability_token)
        if not capability_token:
            raise HTTPException(status_code=401, detail="Invalid or consumed capability token")

        # Check token expiry
        now = datetime.now(UTC).replace(tzinfo=None)
        if now >= capability_token.expires_at:
            raise HTTPException(status_code=401, detail="Capability token expired")

        # Validate file size against token tier
        actual_ciphertext_size = len(base64.b64decode(secret_data.ciphertext))
        if actual_ciphertext_size > capability_token.max_file_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Ciphertext size {actual_ciphertext_size} exceeds token limit "
                f"of {capability_token.max_file_size_bytes} bytes",
            )

        logger.info(
            "capability_token_used",
            token_id=capability_token.id,
            tier=capability_token.tier,
        )
    else:
        # Original PoW validation path
        if not secret_data.pow_proof:
            raise HTTPException(
                status_code=400,
                detail="Either pow_proof or X-Capability-Token header required",
            )

        # Step 1: Validate PoW (does NOT mark challenge as used yet)
        try:
            challenge = validate_pow(
                db=db,
                challenge_id=secret_data.pow_proof.challenge_id,
                nonce=secret_data.pow_proof.nonce,
                counter=secret_data.pow_proof.counter,
                payload_hash=secret_data.pow_proof.payload_hash,
            )
        except ValueError as e:
            logger.warning("pow_validation_failed", error=str(e))
            raise HTTPException(status_code=400, detail=str(e))

        # Step 2: Verify payload hash matches actual ciphertext
        # This prevents solving PoW for one payload and submitting another
        computed_hash = compute_payload_hash(
            secret_data.ciphertext,
            secret_data.iv,
            secret_data.auth_tag,
        )
        if computed_hash != secret_data.pow_proof.payload_hash:
            logger.warning("payload_hash_mismatch")
            raise HTTPException(
                status_code=400,
                detail="Payload hash mismatch - ciphertext doesn't match PoW proof",
            )

        # Step 3: Verify ciphertext size is within PoW limits
        actual_ciphertext_size = len(base64.b64decode(secret_data.ciphertext))
        if actual_ciphertext_size > settings.max_ciphertext_size:
            raise HTTPException(
                status_code=400,
                detail=f"Ciphertext size {actual_ciphertext_size} exceeds limit of "
                f"{settings.max_ciphertext_size} bytes. Use a capability token for larger files.",
            )

        # Step 4: Verify difficulty is sufficient for actual payload size
        # Allows "overpay" (solving harder challenge than needed) but rejects "underpay"
        expected_difficulty = compute_expected_difficulty(actual_ciphertext_size)
        if challenge.difficulty < expected_difficulty:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient PoW difficulty for payload size: "
                f"got {challenge.difficulty}, need {expected_difficulty}",
            )

    # Step 5: Create the secret (may still fail on other validations)
    secret = create_secret(
        db=db,
        ciphertext_b64=secret_data.ciphertext,
        iv_b64=secret_data.iv,
        auth_tag_b64=secret_data.auth_tag,
        unlock_at=secret_data.unlock_at,
        edit_token=secret_data.edit_token,
        decrypt_token=secret_data.decrypt_token,
        expires_at=secret_data.expires_at,
    )

    # Step 5b: Link any pre-uploaded attachments to the secret
    if secret_data.attachment_ids:
        linked_count = link_attachments_to_secret(db, secret.id, secret_data.attachment_ids)
        if linked_count != len(secret_data.attachment_ids):
            # All-or-nothing: if not all attachments could be linked, fail the request
            # This can happen if attachments were deleted, already linked, or don't exist
            # Clean up: unlink any attachments that were linked and delete the secret
            from app.models.secret_attachment import SecretAttachment

            db.query(SecretAttachment).filter(SecretAttachment.secret_id == secret.id).update(
                {"secret_id": None}, synchronize_session=False
            )
            db.delete(secret)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail=f"Failed to link {len(secret_data.attachment_ids) - linked_count} of "
                f"{len(secret_data.attachment_ids)} attachments. "
                "Attachments may have been deleted or already linked to another secret.",
            )
        logger.info(
            "attachments_linked",
            secret_id=secret.id,
            count=linked_count,
        )

    # Step 6: Mark PoW challenge or capability token as consumed
    if capability_token:
        consume_capability_token(db, capability_token, secret.id)
        logger.info(
            "secret_created_with_token",
            secret_id=secret.id,
            ciphertext_size=secret.ciphertext_size,
            tier=capability_token.tier,
        )
    else:
        mark_challenge_used(db, challenge)
        logger.info(
            "secret_created",
            secret_id=secret.id,
            ciphertext_size=secret.ciphertext_size,
            difficulty=challenge.difficulty,
        )

    return SecretCreateResponse(
        secret_id=secret.id,
        unlock_at=secret.unlock_at,
        expires_at=secret.expires_at,
        created_at=secret.created_at,
    )


@router.put("/secrets/edit", response_model=SecretEditResponse)
@limiter.limit(settings.rate_limit_retrieves)
async def edit_secret(
    request: Request,
    edit_data: SecretEditRequest,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    """
    Extend the unlock date of a secret.

    Requires the edit token in the Authorization header.
    """
    edit_token = extract_bearer_token(authorization)

    secret = find_secret_by_edit_token(db, edit_token)
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    try:
        updated_secret = update_secret_dates(db, secret, edit_data.unlock_at, edit_data.expires_at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("secret_edited", secret_id=updated_secret.id)

    return SecretEditResponse(
        secret_id=updated_secret.id,
        unlock_at=updated_secret.unlock_at,
        expires_at=updated_secret.expires_at,
    )


@router.get("/secrets/retrieve", response_model=SecretRetrieveResponse)
@limiter.limit(settings.rate_limit_retrieves)
async def retrieve_secret_endpoint(
    request: Request,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    storage_service: ObjectStorageService = Depends(get_storage_service),
):
    """
    Retrieve a secret's encrypted content.

    This is a ONE-TIME operation. After successful retrieval post-unlock,
    the secret is permanently deleted.

    If the secret has attachments and object storage is enabled, presigned
    download URLs are included in the response. These URLs are valid for 5 minutes.
    """
    decrypt_token = extract_bearer_token(authorization)

    secret = find_secret_by_decrypt_token(db, decrypt_token)
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    # Check secret status BEFORE any destructive operations
    now = datetime.now(UTC).replace(tzinfo=None)

    if secret.retrieved_at is not None:
        # Defense-in-depth: normally unreachable because find_secret_by_decrypt_token
        # excludes deleted secrets, but kept for race condition safety
        logger.warning("secret_already_retrieved", secret_id=secret.id)
        raise HTTPException(
            status_code=410,
            detail={
                "status": "retrieved",
                "message": "This secret has already been retrieved and is no longer available",
            },
        )

    if now >= secret.expires_at:
        logger.warning("secret_expired", secret_id=secret.id)
        raise HTTPException(
            status_code=410,
            detail={
                "status": "expired",
                "expires_at": secret.expires_at.isoformat(),
                "message": "This secret has expired and is no longer available",
            },
        )

    if now < secret.unlock_at:
        logger.warning("secret_access_pending", secret_id=secret.id)
        raise HTTPException(
            status_code=403,
            detail={
                "status": "pending",
                "unlock_at": secret.unlock_at.isoformat(),
                "message": "Secret not yet available",
            },
        )

    # Generate presigned URLs for attachments BEFORE the destructive retrieve operation
    # This ensures that if presigning fails, the secret is NOT deleted
    presigned_urls: dict[str, str] = {}
    if secret.attachments:
        for attachment in secret.attachments:
            try:
                presigned_url = await storage_service.generate_presigned_url(
                    object_key=attachment.storage_key,
                    expires_in=300,  # 5 minutes
                )
                presigned_urls[attachment.storage_key] = presigned_url
            except Exception as e:
                logger.error(
                    "presigned_url_generation_failed",
                    storage_key=attachment.storage_key[:20],
                    error=str(e),
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to generate attachment download URLs",
                )

    # Now safe to perform the destructive retrieve (marks secret as deleted)
    result = retrieve_secret(db, secret)

    # Attach pre-generated presigned URLs to the response
    if result.get("attachments"):
        for attachment in result["attachments"]:
            attachment["presigned_url"] = presigned_urls[attachment["storage_key"]]

    logger.info("secret_retrieved", secret_id=secret.id)
    return SecretRetrieveResponse(**result)


@router.get("/secrets/status", response_model=SecretStatusResponse)
@limiter.limit(settings.rate_limit_retrieves)
async def get_status(
    request: Request,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    """
    Check the status of a secret without triggering one-time deletion.

    Useful for showing countdown timers in the UI.
    """
    decrypt_token = extract_bearer_token(authorization)

    secret = find_secret_by_decrypt_token(db, decrypt_token)
    if not secret:
        return SecretStatusResponse(exists=False, status="not_found")

    status = get_secret_status(db, secret)
    return SecretStatusResponse(**status)


@router.get("/secrets/edit/status", response_model=SecretStatusResponse)
@limiter.limit(settings.rate_limit_retrieves)
async def get_edit_status(
    request: Request,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    """
    Check the status of a secret using the edit token.

    Used by the edit page to display current unlock date.
    """
    edit_token = extract_bearer_token(authorization)

    secret = find_secret_by_edit_token(db, edit_token)
    if not secret:
        return SecretStatusResponse(exists=False, status="not_found")

    status = get_secret_status(db, secret)
    return SecretStatusResponse(**status)


@router.get("/secrets/{secret_id}/status", response_model=SecretIdStatusResponse)
@limiter.limit(settings.rate_limit_retrieves)
async def get_status_by_id(
    request: Request,
    secret_id: str,
    db: Session = Depends(get_db),
):
    """
    Public status endpoint by secret ID.

    Intended for the vault dashboard to refresh status without requiring tokens.

    Note: This endpoint intentionally reveals whether a secret exists and its timing metadata
    (unlock/expires) to anyone with the secret ID; it is rate-limited to reduce enumeration risk.
    """
    secret = find_secret_by_id(db, secret_id)
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    status = get_secret_status(db, secret)
    mapped_status = "unlocked" if status["status"] == "available" else status["status"]

    return SecretIdStatusResponse(
        id=secret.id,
        status=mapped_status,
        unlock_at=secret.unlock_at,
        expires_at=secret.expires_at,
    )
