import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.challenge import Challenge


def compute_payload_hash(ciphertext_b64: str, iv_b64: str, auth_tag_b64: str) -> str:
    """
    Compute SHA-256 hash of the payload for PoW binding verification.

    Hash is computed over: ciphertext || iv || auth_tag (raw bytes)
    """
    ciphertext = base64.b64decode(ciphertext_b64)
    iv = base64.b64decode(iv_b64)
    auth_tag = base64.b64decode(auth_tag_b64)
    return hashlib.sha256(ciphertext + iv + auth_tag).hexdigest()


def compute_expected_difficulty(ciphertext_size: int) -> int:
    """
    Compute the expected PoW difficulty for a given payload size.

    This is used both for challenge generation and for validation at secret creation.
    """
    size_factor = min(ciphertext_size // 100_000, 4)
    return settings.pow_base_difficulty + size_factor


def generate_challenge(db: Session, payload_hash: str, ciphertext_size: int) -> Challenge:
    """Generate a new proof-of-work challenge."""
    nonce = secrets.token_hex(32)  # 64 hex characters

    # Dynamic difficulty based on ciphertext size
    difficulty = compute_expected_difficulty(ciphertext_size)

    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=settings.pow_challenge_ttl_seconds
    )

    challenge = Challenge(
        nonce=nonce,
        difficulty=difficulty,
        payload_hash=payload_hash,
        expires_at=expires_at,
    )

    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    return challenge


def validate_pow(
    db: Session, challenge_id: uuid.UUID, nonce: str, counter: int, payload_hash: str
) -> Challenge:
    """
    Validate a proof-of-work solution WITHOUT marking the challenge as used.

    Returns the Challenge if valid, raises ValueError with specific message if invalid.
    Use mark_challenge_used() after all other validations pass.
    """
    stmt = select(Challenge).where(Challenge.id == challenge_id)
    challenge = db.scalars(stmt).first()

    if not challenge:
        raise ValueError("Challenge not found")

    if challenge.is_used:
        raise ValueError("Challenge already used")

    if datetime.now(UTC).replace(tzinfo=None) > challenge.expires_at:
        raise ValueError("Challenge expired")

    if challenge.nonce != nonce:
        raise ValueError("Nonce mismatch")

    if challenge.payload_hash != payload_hash:
        raise ValueError("Payload hash mismatch")

    # Reconstruct and verify hash
    # Format: nonce || counter (16 hex chars, zero-padded) || payload_hash
    preimage = f"{nonce}{counter:016x}{payload_hash}"
    hash_bytes = hashlib.sha256(preimage.encode()).digest()
    hash_int = int.from_bytes(hash_bytes, "big")

    # Check difficulty (number of leading zero bits)
    target = 2 ** (256 - challenge.difficulty)
    if hash_int >= target:
        raise ValueError("Insufficient proof of work")

    return challenge


def mark_challenge_used(db: Session, challenge: Challenge) -> None:
    """
    Mark a challenge as used after all validations pass.

    Call this only after the secret has been successfully created.
    """
    challenge.is_used = True
    db.commit()


def cleanup_expired_challenges(db: Session) -> int:
    """Delete expired challenges. Returns count of deleted rows."""
    stmt = sa_delete(Challenge).where(Challenge.expires_at < datetime.now(UTC).replace(tzinfo=None))
    result = db.execute(stmt)
    db.commit()
    return result.rowcount
