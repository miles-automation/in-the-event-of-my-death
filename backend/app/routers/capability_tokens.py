import secrets

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.capability_token import (
    CapabilityTokenCreateOut,
    CapabilityTokenIn,
    CapabilityTokenValidateOut,
)
from app.services.capability_token_service import (
    create_capability_token,
    validate_capability_token,
)

router = APIRouter(tags=["capability-tokens"])
logger = structlog.get_logger()


def verify_internal_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Verify internal API key for token creation."""
    if not settings.internal_api_key:
        raise HTTPException(status_code=503, detail="Token creation not configured")
    if not secrets.compare_digest(x_api_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/capability-tokens", response_model=CapabilityTokenCreateOut, status_code=201)
@limiter.limit(settings.rate_limit_token_create)
async def create_token(
    request: Request,
    token_data: CapabilityTokenIn,
    db: Session = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
):
    """
    Create a new capability token (internal endpoint).

    Called by payment webhooks after successful payment, or manually for testing/promos.
    Requires X-API-Key header with internal API key.
    """
    try:
        token_model, raw_token = create_capability_token(
            db=db,
            tier=token_data.tier,
            payment_provider=token_data.payment_provider,
            payment_reference=token_data.payment_reference,
            token_metadata=token_data.token_metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        "capability_token_created",
        token_id=token_model.id,
        tier=token_model.tier,
        payment_provider=token_data.payment_provider,
    )

    return CapabilityTokenCreateOut(
        token=raw_token,
        tier=token_model.tier,
        max_file_size_bytes=token_model.max_file_size_bytes,
        max_expiry_days=token_model.max_expiry_days,
        expires_at=token_model.expires_at,
        token_metadata=token_model.token_metadata,
    )


@router.get("/capability-tokens/validate", response_model=CapabilityTokenValidateOut)
@limiter.limit(settings.rate_limit_token_validate)
async def validate_token(
    request: Request,
    x_capability_token: str = Header(..., alias="X-Capability-Token"),
    db: Session = Depends(get_db),
):
    """
    Validate a capability token without consuming it.

    Returns tier information if valid. Does not consume the token.
    """
    if len(x_capability_token) != 64:
        return CapabilityTokenValidateOut(valid=False, error="Invalid token format")

    result = validate_capability_token(db, x_capability_token)

    return CapabilityTokenValidateOut(**result)
