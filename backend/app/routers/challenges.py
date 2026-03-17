import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.challenge import ChallengeCreate, ChallengeResponse
from app.services.pow_service import generate_challenge

router = APIRouter(tags=["challenges"])
logger = structlog.get_logger()


@router.post("/challenges", response_model=ChallengeResponse, status_code=201)
@limiter.limit(settings.rate_limit_challenges)
async def create_challenge(
    request: Request,
    challenge_data: ChallengeCreate,
    db: Session = Depends(get_db),
):
    """
    Request a proof-of-work challenge.

    The client must solve this challenge before creating a secret.
    """
    challenge = generate_challenge(
        db=db,
        payload_hash=challenge_data.payload_hash,
        ciphertext_size=challenge_data.ciphertext_size,
    )

    logger.info(
        "challenge_created",
        challenge_id=challenge.id,
        difficulty=challenge.difficulty,
        ciphertext_size=challenge_data.ciphertext_size,
    )

    return ChallengeResponse(
        challenge_id=challenge.id,
        nonce=challenge.nonce,
        difficulty=challenge.difficulty,
        expires_at=challenge.expires_at,
        algorithm="sha256",
    )
