import base64
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.secret import Secret
from app.services.crypto_utils import hash_token, verify_token

TOKEN_PREFIX_LENGTH = 16  # First 16 hex chars (64 bits) of token


def get_token_prefix(token: str) -> str:
    """Extract the prefix from a token for indexed lookup."""
    return token[:TOKEN_PREFIX_LENGTH]


def create_secret(
    db: Session,
    ciphertext_b64: str,
    iv_b64: str,
    auth_tag_b64: str,
    unlock_at: datetime,
    edit_token: str,
    decrypt_token: str,
    expires_at: datetime,
) -> Secret:
    """
    Create a new secret with hashed tokens.

    The tokens are hashed with Argon2id before storage.
    Token prefixes are stored for O(1) lookup.
    """
    ciphertext = base64.b64decode(ciphertext_b64)
    iv = base64.b64decode(iv_b64)
    auth_tag = base64.b64decode(auth_tag_b64)

    secret = Secret(
        ciphertext=ciphertext,
        iv=iv,
        auth_tag=auth_tag,
        unlock_at=unlock_at,
        expires_at=expires_at,
        edit_token_prefix=get_token_prefix(edit_token),
        decrypt_token_prefix=get_token_prefix(decrypt_token),
        edit_token_hash=hash_token(edit_token),
        decrypt_token_hash=hash_token(decrypt_token),
        ciphertext_size=len(ciphertext),
    )

    db.add(secret)
    db.commit()
    db.refresh(secret)

    return secret


def find_secret_by_edit_token(db: Session, edit_token: str) -> Secret | None:
    """Find a secret by its edit token.

    Uses indexed prefix lookup for O(1) database query, then verifies
    with Argon2 hash. Prefix collisions are extremely rare (64 bits)
    but handled correctly by verifying the full hash.
    """
    prefix = get_token_prefix(edit_token)
    candidates = (
        db.query(Secret)
        .filter(
            Secret.edit_token_prefix == prefix,
            Secret.is_deleted == False,  # noqa: E712
        )
        .all()
    )

    for secret in candidates:
        if verify_token(edit_token, secret.edit_token_hash):
            return secret

    return None


def find_secret_by_decrypt_token(db: Session, decrypt_token: str) -> Secret | None:
    """Find a secret by its decrypt token.

    Uses indexed prefix lookup for O(1) database query, then verifies
    with Argon2 hash. Prefix collisions are extremely rare (64 bits)
    but handled correctly by verifying the full hash.
    """
    prefix = get_token_prefix(decrypt_token)
    candidates = (
        db.query(Secret)
        .filter(
            Secret.decrypt_token_prefix == prefix,
            Secret.is_deleted == False,  # noqa: E712
        )
        .all()
    )

    for secret in candidates:
        if verify_token(decrypt_token, secret.decrypt_token_hash):
            return secret

    return None


def find_secret_by_id(db: Session, secret_id: str) -> Secret | None:
    """Find a secret by its ID.

    The secret row is kept even after retrieval/expiry (ciphertext is cleared),
    so ID-based status checks must not filter on `is_deleted`.
    """
    return db.query(Secret).filter(Secret.id == secret_id).first()


def update_secret_dates(
    db: Session, secret: Secret, new_unlock_at: datetime, new_expires_at: datetime
) -> Secret:
    """
    Update the unlock and expiry dates of a secret.

    The new unlock date must be after the current unlock date.
    """
    if new_unlock_at <= secret.unlock_at:
        raise ValueError("New unlock date must be after current unlock date")

    if secret.retrieved_at is not None:
        raise ValueError("Cannot edit a secret that has already been retrieved")

    if datetime.now(UTC).replace(tzinfo=None) >= secret.unlock_at:
        raise ValueError("Cannot edit a secret that has already unlocked")

    secret.unlock_at = new_unlock_at
    secret.expires_at = new_expires_at
    db.commit()
    db.refresh(secret)

    return secret


def retrieve_secret(db: Session, secret: Secret) -> dict:
    """
    Retrieve a secret's encrypted content.

    This is a one-time operation. After retrieval, the secret is marked for deletion.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    # Check if already retrieved
    if secret.retrieved_at is not None:
        return {
            "status": "retrieved",
            "message": "This secret has already been retrieved and is no longer available",
        }

    # Check if expired
    if now >= secret.expires_at:
        return {
            "status": "expired",
            "unlock_at": secret.unlock_at,
            "message": "This secret has expired and is no longer available",
        }

    # Check if unlocked
    if now < secret.unlock_at:
        return {
            "status": "pending",
            "unlock_at": secret.unlock_at,
            "message": "Secret not yet available",
        }

    # Build attachment metadata list
    attachments = []
    for att in secret.attachments:
        attachments.append(
            {
                "storage_key": att.storage_key,
                "encrypted_metadata": base64.b64encode(att.encrypted_metadata).decode(),
                "metadata_iv": base64.b64encode(att.metadata_iv).decode(),
                "metadata_auth_tag": base64.b64encode(att.metadata_auth_tag).decode(),
                "blob_iv": base64.b64encode(att.blob_iv).decode(),
                "blob_auth_tag": base64.b64encode(att.blob_auth_tag).decode(),
                "blob_size": att.blob_size,
                "position": att.position,
            }
        )

    # Capture data before clearing
    result = {
        "status": "available",
        "ciphertext": base64.b64encode(secret.ciphertext).decode(),
        "iv": base64.b64encode(secret.iv).decode(),
        "auth_tag": base64.b64encode(secret.auth_tag).decode(),
        "retrieved_at": now,
        "message": "This secret has been deleted and cannot be retrieved again.",
        "attachments": attachments if attachments else None,
    }

    # Clear ciphertext immediately in the same transaction
    secret.retrieved_at = now
    secret.is_deleted = True
    secret.ciphertext = None
    secret.iv = None
    secret.auth_tag = None
    secret.cleared_at = now
    db.commit()

    return result


def get_secret_status(db: Session, secret: Secret) -> dict:
    """
    Get the status of a secret without triggering one-time deletion.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    if secret.retrieved_at is not None:
        return {
            "exists": True,
            "status": "retrieved",
            "unlock_at": secret.unlock_at,
            "expires_at": secret.expires_at,
        }

    if now >= secret.expires_at:
        return {
            "exists": True,
            "status": "expired",
            "unlock_at": secret.unlock_at,
            "expires_at": secret.expires_at,
        }

    if now >= secret.unlock_at:
        return {
            "exists": True,
            "status": "available",
            "unlock_at": secret.unlock_at,
            "expires_at": secret.expires_at,
        }

    return {
        "exists": True,
        "status": "pending",
        "unlock_at": secret.unlock_at,
        "expires_at": secret.expires_at,
    }


def get_secrets_needing_cleanup(db: Session) -> list[tuple[str, list[str]]]:
    """
    Get secrets that need cleanup along with their attachment storage keys.

    Returns a list of tuples: (secret_id, [storage_keys]).
    Secrets without attachments will have an empty storage_keys list.

    Only returns secrets that are:
    - Expired (expires_at <= now), OR
    - Retrieved (retrieved_at IS NOT NULL)
    And haven't been cleared yet (cleared_at IS NULL).
    """
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload

    now = datetime.now(UTC).replace(tzinfo=None)

    secrets = (
        db.query(Secret)
        .options(joinedload(Secret.attachments))
        .filter(
            Secret.cleared_at == None,  # noqa: E711 - Not already cleared
            or_(
                Secret.expires_at <= now,  # Expired
                Secret.retrieved_at != None,  # noqa: E711 - Retrieved
            ),
        )
        .all()
    )

    return [(secret.id, [att.storage_key for att in secret.attachments]) for secret in secrets]


def clear_secret_and_attachments(db: Session, secret_id: str) -> bool:
    """
    Clear a single secret's ciphertext and delete its attachment rows.

    This should only be called AFTER the corresponding S3 blobs have been
    successfully deleted. The attachment rows are explicitly deleted since
    we UPDATE (not DELETE) the secret, so CASCADE doesn't trigger.

    Returns True if the secret was cleared, False if not found or already cleared.
    """
    from app.models.secret_attachment import SecretAttachment

    now = datetime.now(UTC).replace(tzinfo=None)

    secret = db.query(Secret).filter(Secret.id == secret_id).first()
    if secret is None or secret.cleared_at is not None:
        return False

    # Explicitly delete attachment rows (CASCADE won't trigger on UPDATE)
    db.query(SecretAttachment).filter(SecretAttachment.secret_id == secret_id).delete()

    # Clear the secret's ciphertext
    secret.ciphertext = None
    secret.iv = None
    secret.auth_tag = None
    secret.cleared_at = now

    db.commit()
    return True


def clear_expired_secrets(db: Session) -> tuple[int, list[str]]:
    """
    Clear secrets' ciphertext while preserving metadata for analytics.

    DEPRECATED: Use get_secrets_needing_cleanup() + clear_secret_and_attachments()
    for proper blob cleanup. This function is kept for backwards compatibility
    with secrets that have no attachments.

    Clears secrets that are either:
    - Expired (expires_at <= now), OR
    - Retrieved (retrieved_at IS NOT NULL)

    And haven't been cleared yet (cleared_at IS NULL).

    Sets ciphertext/iv/auth_tag to None and cleared_at to current time.
    Rows are never deleted - metadata is preserved for analytics.

    Returns a tuple of (count of cleared secrets, empty list for compatibility).
    """
    from sqlalchemy import or_

    now = datetime.now(UTC).replace(tzinfo=None)

    result = (
        db.query(Secret)
        .filter(
            Secret.cleared_at == None,  # noqa: E711 - Not already cleared
            or_(
                Secret.expires_at <= now,  # Expired
                Secret.retrieved_at != None,  # noqa: E711 - Retrieved
            ),
        )
        .update(
            {
                "ciphertext": None,
                "iv": None,
                "auth_tag": None,
                "cleared_at": now,
            }
        )
    )
    db.commit()
    return result, []
