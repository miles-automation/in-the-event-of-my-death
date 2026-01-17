import re

from pydantic import BaseModel, Field, field_validator


def strict_base64_decode(value: str, field_name: str) -> bytes:
    """
    Strictly validate and decode base64 string.

    Rejects strings with invalid characters, incorrect padding, or whitespace.
    """
    import base64

    if not re.match(r"^[A-Za-z0-9+/]*={0,2}$", value):
        raise ValueError(f"{field_name}: Invalid base64 characters")
    if len(value) % 4 != 0:
        raise ValueError(f"{field_name}: Invalid base64 length (must be multiple of 4)")
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        raise ValueError(f"{field_name}: Invalid base64 encoding")


class AttachmentUploadRequest(BaseModel):
    """Request to upload an encrypted file attachment to object storage."""

    encrypted_blob: str = Field(..., description="Base64 encoded encrypted file bytes")
    blob_iv: str = Field(..., description="Base64 encoded 12-byte IV for blob encryption")
    blob_auth_tag: str = Field(..., description="Base64 encoded 16-byte auth tag for blob")
    encrypted_metadata: str = Field(..., description="Base64 encoded encrypted metadata JSON")
    metadata_iv: str = Field(..., description="Base64 encoded 12-byte IV for metadata encryption")
    metadata_auth_tag: str = Field(..., description="Base64 encoded 16-byte auth tag for metadata")
    position: int = Field(default=0, ge=0, description="Ordering index for multiple attachments")

    @field_validator("encrypted_blob")
    @classmethod
    def validate_encrypted_blob(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "encrypted_blob")
        if len(decoded) < 1:
            raise ValueError("encrypted_blob cannot be empty")
        return v

    @field_validator("blob_iv")
    @classmethod
    def validate_blob_iv(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "blob_iv")
        if len(decoded) != 12:
            raise ValueError("blob_iv must be exactly 12 bytes")
        return v

    @field_validator("blob_auth_tag")
    @classmethod
    def validate_blob_auth_tag(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "blob_auth_tag")
        if len(decoded) != 16:
            raise ValueError("blob_auth_tag must be exactly 16 bytes")
        return v

    @field_validator("encrypted_metadata")
    @classmethod
    def validate_encrypted_metadata(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "encrypted_metadata")
        if len(decoded) < 1:
            raise ValueError("encrypted_metadata cannot be empty")
        return v

    @field_validator("metadata_iv")
    @classmethod
    def validate_metadata_iv(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "metadata_iv")
        if len(decoded) != 12:
            raise ValueError("metadata_iv must be exactly 12 bytes")
        return v

    @field_validator("metadata_auth_tag")
    @classmethod
    def validate_metadata_auth_tag(cls, v: str) -> str:
        decoded = strict_base64_decode(v, "metadata_auth_tag")
        if len(decoded) != 16:
            raise ValueError("metadata_auth_tag must be exactly 16 bytes")
        return v


class AttachmentUploadResponse(BaseModel):
    """Response after successfully uploading an attachment."""

    storage_key: str
    attachment_id: str


class AttachmentUrlRequest(BaseModel):
    """Request to get a presigned URL for downloading an attachment."""

    # No body needed - storage_key comes from path, auth from header
    pass


class AttachmentUrlResponse(BaseModel):
    """Response containing a presigned URL for downloading an attachment."""

    presigned_url: str
    expires_in: int = Field(default=300, description="URL expiry time in seconds")


class AttachmentMetadata(BaseModel):
    """Attachment metadata returned when retrieving a secret."""

    storage_key: str
    encrypted_metadata: str  # Base64
    metadata_iv: str  # Base64
    metadata_auth_tag: str  # Base64
    blob_iv: str  # Base64
    blob_auth_tag: str  # Base64
    blob_size: int
    position: int
