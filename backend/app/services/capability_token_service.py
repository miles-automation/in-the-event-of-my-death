import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.capability_token import CapabilityToken
from app.services.crypto_utils import hash_token, verify_token

TOKEN_PREFIX_LENGTH = 16


def get_token_prefix(token: str) -> str:
    """Extract the prefix from a token for indexed lookup."""
    return token[:TOKEN_PREFIX_LENGTH]


def get_tier_config(tier: str) -> dict | None:
    """Get configuration for a tier."""
    return settings.capability_tiers.get(tier)


def create_capability_token(
    db: Session,
    tier: str,
    payment_provider: str | None = None,
    payment_reference: str | None = None,
    token_metadata: dict | None = None,
) -> tuple[CapabilityToken, str]:
    """
    Create a new capability token.

    Returns tuple of (token_model, raw_token).
    The raw_token is only available at creation time.
    """
    tier_config = get_tier_config(tier)
    if not tier_config:
        raise ValueError(f"Invalid tier: {tier}")

    # Generate secure random token (64 hex chars = 256 bits)
    raw_token = secrets.token_hex(32)

    # Token expires 5 years from creation - user can use whenever ready
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5 * 365)

    token = CapabilityToken(
        token_prefix=get_token_prefix(raw_token),
        token_hash=hash_token(raw_token),
        tier=tier,
        max_file_size_bytes=tier_config["max_file_size_bytes"],
        max_expiry_days=tier_config["max_expiry_days"],
        expires_at=expires_at,
        payment_provider=payment_provider,
        payment_reference=payment_reference,
        token_metadata=token_metadata,
    )

    db.add(token)
    db.commit()
    db.refresh(token)

    return token, raw_token


def find_capability_token(db: Session, raw_token: str) -> CapabilityToken | None:
    """
    Find a capability token by its raw value.

    Uses indexed prefix lookup, then Argon2 verification.
    Returns None if not found or already consumed.
    """
    prefix = get_token_prefix(raw_token)
    stmt = select(CapabilityToken).where(
        CapabilityToken.token_prefix == prefix,
        CapabilityToken.consumed_at == None,  # noqa: E711 - SQLAlchemy requires ==
    )
    candidates = db.scalars(stmt).all()

    for token in candidates:
        if verify_token(raw_token, token.token_hash):
            return token

    return None


def validate_capability_token(db: Session, raw_token: str) -> dict:
    """
    Validate a capability token without consuming it.

    Returns dict with validation result and tier info.
    """
    token = find_capability_token(db, raw_token)

    if token is None:
        # Check if it was already consumed
        prefix = get_token_prefix(raw_token)
        stmt = select(CapabilityToken).where(
            CapabilityToken.token_prefix == prefix,
            CapabilityToken.consumed_at != None,  # noqa: E711
        )
        consumed_candidates = db.scalars(stmt).all()
        for consumed in consumed_candidates:
            if verify_token(raw_token, consumed.token_hash):
                return {"valid": False, "consumed": True, "error": "Token already consumed"}
        return {"valid": False, "error": "Token not found"}

    now = datetime.now(UTC).replace(tzinfo=None)
    if now >= token.expires_at:
        return {"valid": False, "error": "Token expired"}

    return {
        "valid": True,
        "tier": token.tier,
        "max_file_size_bytes": token.max_file_size_bytes,
        "max_expiry_days": token.max_expiry_days,
        "expires_at": token.expires_at,
        "consumed": False,
    }


def consume_capability_token(
    db: Session,
    token: CapabilityToken,
    secret_id: uuid.UUID,
) -> None:
    """
    Mark a capability token as consumed.

    Called after successful secret creation.
    """
    token.consumed_at = datetime.now(UTC).replace(tzinfo=None)
    token.consumed_by_secret_id = secret_id
    db.commit()
