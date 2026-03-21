import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChallengeIn(BaseModel):
    payload_hash: str = Field(
        ..., min_length=64, max_length=64, description="SHA256 hex of payload"
    )
    ciphertext_size: int = Field(..., gt=0, description="Size in bytes for difficulty scaling")


class ChallengeOut(BaseModel):
    challenge_id: uuid.UUID
    nonce: str
    difficulty: int
    expires_at: datetime
    algorithm: str = "sha256"
