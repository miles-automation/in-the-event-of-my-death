import structlog
from fastapi import APIRouter, Request

from app.config import settings
from app.middleware.rate_limit import limiter
from app.schemas.feedback import FeedbackCreate, FeedbackResponse
from app.services.matrix_service import send_feedback_notification

router = APIRouter()
logger = structlog.get_logger()


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
@limiter.limit(settings.rate_limit_feedback)
async def submit_feedback(
    request: Request,
    feedback: FeedbackCreate,
):
    """
    Submit user feedback.

    Feedback is forwarded to Matrix for visibility.
    No database storage - just notification.
    """
    # Send to Matrix (best effort - don't fail if notification fails)
    await send_feedback_notification(
        message=feedback.message,
        email=feedback.email,
    )

    logger.info(
        "feedback_submitted",
        has_email=feedback.email is not None,
        message_length=len(feedback.message),
    )

    return FeedbackResponse(
        success=True,
        message="Thank you for your feedback!",
    )
