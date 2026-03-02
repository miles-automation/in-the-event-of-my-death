import re

from pydantic import BaseModel, Field, field_validator


class VaultPutRequest(BaseModel):
    ciphertext: str = Field(..., description="Base64-encoded encrypted vault blob")

    @field_validator("ciphertext")
    @classmethod
    def validate_ciphertext(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9+/]*={0,2}$", v):
            raise ValueError("Invalid base64 characters")
        if len(v) % 4 != 0:
            raise ValueError("Invalid base64 length")
        return v


class VaultGetResponse(BaseModel):
    ciphertext: str
    etag: str


class VaultPutResponse(BaseModel):
    etag: str
    created: bool
