import base64
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator

from app.config import settings

# Types for server-side preset calculations
UnlockPresetType = Literal["now", "15m", "1h", "24h", "1w"]
ExpiryPresetType = Literal["15m", "1h", "24h", "1w"]


def serialize_datetime_utc(dt: datetime) -> str:
    """Serialize datetime as ISO format with Z suffix to indicate UTC."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


# Custom type that serializes naive datetimes with Z suffix
UTCDateTime = Annotated[datetime, PlainSerializer(serialize_datetime_utc)]


def strict_base64_decode(value: str, field_name: str) -> bytes:
    """
    Strictly validate and decode base64 string.

    Rejects strings with invalid characters, incorrect padding, or whitespace.
    """
    # Check for valid base64 characters only (no whitespace allowed)
    if not re.match(r"^[A-Za-z0-9+/]*={0,2}$", value):
        raise ValueError(f"{field_name}: Invalid base64 characters")
    # Check length is multiple of 4
    if len(value) % 4 != 0:
        raise ValueError(f"{field_name}: Invalid base64 length (must be multiple of 4)")
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        raise ValueError(f"{field_name}: Invalid base64 encoding")


class PowProof(BaseModel):
    challenge_id: str
    nonce: str = Field(..., min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    counter: int = Field(..., ge=0)
    payload_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class SecretCreate(BaseModel):
    ciphertext: str = Field(..., description="Base64 encoded ciphertext")
    iv: str = Field(..., description="Base64 encoded 12-byte IV")
    auth_tag: str = Field(..., description="Base64 encoded 16-byte auth tag")
    unlock_at: datetime | None = None  # Optional when unlock_preset is provided
    unlock_preset: UnlockPresetType | None = None  # Server calculates unlock_at from this
    expires_at: datetime | None = None  # Optional when expiry_preset is provided
    expiry_preset: ExpiryPresetType | None = None  # Server calculates expires_at from this
    edit_token: str = Field(..., min_length=64, max_length=64, description="Hex token")
    decrypt_token: str = Field(..., min_length=64, max_length=64, description="Hex token")
    pow_proof: PowProof | None = None  # Optional when using capability token
    attachment_ids: list[str] | None = None  # IDs of pre-uploaded attachments

    @field_validator("ciphertext")
    @classmethod
    def validate_ciphertext_base64(cls, v: str) -> str:
        # Only validate base64 format here. Size validation is done in the router
        # because the limit depends on whether PoW or capability token is used.
        decoded = strict_base64_decode(v, "ciphertext")
        if len(decoded) < 1:
            raise ValueError("Ciphertext cannot be empty")
        return v

    @field_validator("iv")
    @classmethod
    def validate_iv(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "iv")
        if len(decoded) != 12:
            raise ValueError("IV must be exactly 12 bytes")
        return v

    @field_validator("auth_tag")
    @classmethod
    def validate_auth_tag(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "auth_tag")
        if len(decoded) != 16:
            raise ValueError("Auth tag must be exactly 16 bytes")
        return v

    @field_validator("unlock_at")
    @classmethod
    def validate_unlock_at(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None  # Will be set from unlock_preset in model_validator
        now = datetime.now(UTC).replace(tzinfo=None)
        min_unlock = now + timedelta(minutes=settings.min_unlock_minutes)
        max_unlock = now + timedelta(days=settings.max_unlock_days)

        # Convert to naive UTC for storage
        v_naive = v.replace(tzinfo=None) if v.tzinfo else v

        if v_naive < min_unlock:
            if settings.min_unlock_minutes == 0:
                raise ValueError("Unlock date cannot be in the past")
            else:
                min_mins = settings.min_unlock_minutes
                raise ValueError(f"Unlock date must be at least {min_mins} minutes in the future")
        if v_naive > max_unlock:
            raise ValueError(f"Unlock date cannot exceed {settings.max_unlock_days} days")
        return v_naive

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None  # Will be set from expiry_preset in model_validator
        now = datetime.now(UTC).replace(tzinfo=None)
        max_expiry = now + timedelta(days=settings.max_expiry_days)

        # Convert to naive UTC for storage
        v_naive = v.replace(tzinfo=None) if v.tzinfo else v

        if v_naive > max_expiry:
            raise ValueError(f"Expiry date cannot exceed {settings.max_expiry_days} days")
        return v_naive

    @model_validator(mode="after")
    def validate_and_compute_dates(self) -> "SecretCreate":
        now = datetime.now(UTC).replace(tzinfo=None)

        # Calculate unlock_at from preset if provided
        if self.unlock_preset is not None:
            if self.unlock_preset == "now":
                self.unlock_at = now
            elif self.unlock_preset == "15m":
                self.unlock_at = now + timedelta(minutes=15)
            elif self.unlock_preset == "1h":
                self.unlock_at = now + timedelta(hours=1)
            elif self.unlock_preset == "24h":
                self.unlock_at = now + timedelta(hours=24)
            elif self.unlock_preset == "1w":
                self.unlock_at = now + timedelta(weeks=1)

        # Ensure unlock_at is set (either directly or from preset)
        if self.unlock_at is None:
            raise ValueError("Either unlock_at or unlock_preset must be provided")

        # Validate preset-computed unlock_at against max bounds
        # (min bounds are implicitly valid since presets are all >= now)
        max_unlock = now + timedelta(days=settings.max_unlock_days)
        if self.unlock_at > max_unlock:
            raise ValueError(f"Unlock date cannot exceed {settings.max_unlock_days} days")

        # Calculate expires_at from preset if provided (relative to unlock_at)
        if self.expiry_preset is not None:
            if self.expiry_preset == "15m":
                self.expires_at = self.unlock_at + timedelta(minutes=15)
            elif self.expiry_preset == "1h":
                self.expires_at = self.unlock_at + timedelta(hours=1)
            elif self.expiry_preset == "24h":
                self.expires_at = self.unlock_at + timedelta(hours=24)
            elif self.expiry_preset == "1w":
                self.expires_at = self.unlock_at + timedelta(weeks=1)

        # Ensure expires_at is set (either directly or from preset)
        if self.expires_at is None:
            raise ValueError("Either expires_at or expiry_preset must be provided")

        # Validate preset-computed expires_at against max bounds
        max_expiry = now + timedelta(days=settings.max_expiry_days)
        if self.expires_at > max_expiry:
            raise ValueError(f"Expiry date cannot exceed {settings.max_expiry_days} days")

        # Validate expiry constraints
        min_gap = timedelta(minutes=settings.min_expiry_gap_minutes)
        if self.expires_at <= self.unlock_at:
            raise ValueError("expires_at must be after unlock_at")
        if self.expires_at < self.unlock_at + min_gap:
            min_gap_mins = settings.min_expiry_gap_minutes
            raise ValueError(f"expires_at must be at least {min_gap_mins} minutes after unlock_at")
        return self


class SecretCreateResponse(BaseModel):
    secret_id: str
    unlock_at: UTCDateTime
    expires_at: UTCDateTime
    created_at: UTCDateTime


class SecretEditRequest(BaseModel):
    unlock_at: datetime
    expires_at: datetime

    @field_validator("unlock_at")
    @classmethod
    def validate_unlock_at(cls, v: datetime) -> datetime:
        now = datetime.now(UTC).replace(tzinfo=None)
        max_unlock = now + timedelta(days=settings.max_unlock_days)
        v_naive = v.replace(tzinfo=None) if v.tzinfo else v
        if v_naive > max_unlock:
            raise ValueError(f"Unlock date cannot exceed {settings.max_unlock_days} days")
        return v_naive

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime) -> datetime:
        now = datetime.now(UTC).replace(tzinfo=None)
        max_expiry = now + timedelta(days=settings.max_expiry_days)
        v_naive = v.replace(tzinfo=None) if v.tzinfo else v
        if v_naive > max_expiry:
            raise ValueError(f"Expiry date cannot exceed {settings.max_expiry_days} days")
        return v_naive

    @model_validator(mode="after")
    def validate_expiry_constraints(self) -> "SecretEditRequest":
        min_gap = timedelta(minutes=settings.min_expiry_gap_minutes)
        if self.expires_at <= self.unlock_at:
            raise ValueError("expires_at must be after unlock_at")
        if self.expires_at < self.unlock_at + min_gap:
            min_gap_mins = settings.min_expiry_gap_minutes
            raise ValueError(f"expires_at must be at least {min_gap_mins} minutes after unlock_at")
        return self


class SecretEditResponse(BaseModel):
    secret_id: str
    unlock_at: UTCDateTime
    expires_at: UTCDateTime


class SecretStatusResponse(BaseModel):
    exists: bool
    status: Literal["pending", "available", "expired", "retrieved", "not_found"]
    unlock_at: UTCDateTime | None = None
    expires_at: UTCDateTime | None = None  # None only when exists=False


class SecretIdStatusResponse(BaseModel):
    id: str
    # Always True: non-existent secrets return 404 (kept for API consistency).
    exists: Literal[True] = True
    status: Literal["pending", "unlocked", "expired", "retrieved"]
    unlock_at: UTCDateTime
    expires_at: UTCDateTime


class AttachmentMetadataResponse(BaseModel):
    """Attachment metadata returned when retrieving a secret."""

    storage_key: str
    encrypted_metadata: str  # Base64
    metadata_iv: str  # Base64
    metadata_auth_tag: str  # Base64
    blob_iv: str  # Base64
    blob_auth_tag: str  # Base64
    blob_size: int
    position: int
    presigned_url: str  # Presigned download URL (valid for 5 minutes)


class SecretRetrieveResponse(BaseModel):
    status: str
    ciphertext: str | None = None
    iv: str | None = None
    auth_tag: str | None = None
    unlock_at: UTCDateTime | None = None
    retrieved_at: UTCDateTime | None = None
    message: str | None = None
    attachments: list[AttachmentMetadataResponse] | None = None
