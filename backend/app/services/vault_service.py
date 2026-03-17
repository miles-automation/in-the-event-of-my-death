import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.vault import Vault

MAX_VAULT_BLOB_SIZE = 5_000_000  # 5MB


def hash_sync_token(sync_token: str) -> str:
    """SHA-256 hash of syncToken.

    Using SHA-256 (not Argon2) is appropriate here because syncToken
    is a full 256-bit random value — brute force is computationally
    infeasible regardless of hash speed.
    """
    return hashlib.sha256(sync_token.encode()).hexdigest()


def verify_sync_token(vault: Vault, sync_token: str) -> bool:
    """Constant-time comparison of syncToken hash."""
    expected = vault.sync_token_hash
    provided = hash_sync_token(sync_token)
    return hmac.compare_digest(expected, provided)


def get_vault(db: Session, vault_id: str) -> Vault | None:
    return db.query(Vault).filter(Vault.vault_id == vault_id).first()


def get_vault_or_404(db: Session, vault_id: str, sync_token: str) -> Vault:
    """Lookup vault by ID and verify sync token, or raise 404.

    Returns 404 for both missing vaults and invalid sync tokens to avoid
    confirming vault existence to unauthenticated callers.
    """
    vault = get_vault(db, vault_id)
    if not vault or not verify_sync_token(vault, sync_token):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vault not found")
    return vault


def create_vault(
    db: Session,
    vault_id: str,
    ciphertext_b64: str,
    sync_token: str,
) -> tuple[Vault, str]:
    """Create a new vault. Returns (vault, etag). Raises ValueError if exists."""
    existing = get_vault(db, vault_id)
    if existing:
        raise ValueError("Vault already exists")

    ciphertext = base64.b64decode(ciphertext_b64)
    if len(ciphertext) > MAX_VAULT_BLOB_SIZE:
        raise ValueError(f"Vault blob exceeds {MAX_VAULT_BLOB_SIZE} byte limit")

    etag = str(uuid.uuid4())
    vault = Vault(
        vault_id=vault_id,
        ciphertext=ciphertext,
        etag=etag,
        sync_token_hash=hash_sync_token(sync_token),
        ciphertext_size=len(ciphertext),
    )
    db.add(vault)
    db.commit()
    db.refresh(vault)
    return vault, etag


def update_vault(
    db: Session,
    vault: Vault,
    ciphertext_b64: str,
    if_match_etag: str,
) -> tuple[Vault, str]:
    """Update vault blob with ETag concurrency. Raises ValueError on conflict."""
    if vault.etag != if_match_etag:
        raise ValueError("ETag mismatch — vault was modified by another device")

    ciphertext = base64.b64decode(ciphertext_b64)
    if len(ciphertext) > MAX_VAULT_BLOB_SIZE:
        raise ValueError(f"Vault blob exceeds {MAX_VAULT_BLOB_SIZE} byte limit")

    new_etag = str(uuid.uuid4())
    vault.ciphertext = ciphertext
    vault.etag = new_etag
    vault.ciphertext_size = len(ciphertext)
    vault.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(vault)
    return vault, new_etag
