from pydantic import BaseModel, Field

from app.schemas.secret import UTCDateTime


class CapabilityTokenIn(BaseModel):
    """Internal request to create a capability token (from payment webhook or manual)."""

    tier: str = Field(..., pattern="^(basic|standard|large)$")
    payment_provider: str | None = None
    payment_reference: str | None = None
    token_metadata: dict | None = None


class CapabilityTokenCreateOut(BaseModel):
    """Response containing the raw token (only returned once at creation)."""

    token: str  # Raw token - only returned at creation time
    tier: str
    max_file_size_bytes: int
    max_expiry_days: int
    expires_at: UTCDateTime
    token_metadata: dict | None = None


class CapabilityTokenValidateOut(BaseModel):
    """Response for token validation (without consuming)."""

    valid: bool
    tier: str | None = None
    max_file_size_bytes: int | None = None
    max_expiry_days: int | None = None
    expires_at: UTCDateTime | None = None
    consumed: bool = False
    error: str | None = None
