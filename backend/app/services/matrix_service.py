"""Matrix notification service for operational alerts."""

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

# Rate limiting for error alerts to prevent alert storms
_last_alert_time: datetime | None = None
_alert_cooldown = timedelta(seconds=30)
_alert_lock = threading.Lock()


def _env_prefix() -> tuple[str, str]:
    """Return (emoji, env_name) for alert formatting."""
    env = settings.environment.lower()
    emoji = {"production": "🔴", "staging": "🟡", "development": "🟢"}.get(env, "⚪")
    return emoji, settings.environment


def _should_send_alert() -> bool:
    """Check if we should send an alert (rate limiting)."""
    global _last_alert_time
    with _alert_lock:
        now = datetime.now(UTC)
        if _last_alert_time and (now - _last_alert_time) < _alert_cooldown:
            return False
        _last_alert_time = now
        return True


def reset_alert_rate_limit() -> None:
    """Reset the rate limit state. Used in tests."""
    global _last_alert_time
    with _alert_lock:
        _last_alert_time = None


def _build_matrix_url() -> str | None:
    """Build the Matrix message send URL."""
    if not all([settings.matrix_homeserver_url, settings.matrix_room_id]):
        return None
    txn_id = str(uuid4())
    return (
        f"{settings.matrix_homeserver_url}/_matrix/client/r0/rooms/"
        f"{settings.matrix_room_id}/send/m.room.message/{txn_id}"
    )


def _get_auth_headers() -> dict:
    """Get authorization headers for Matrix API."""
    return {"Authorization": f"Bearer {settings.matrix_access_token}"}


async def send_feedback_notification(message: str, email: str | None) -> bool:
    """
    Send feedback notification to Matrix room.

    Returns True if notification was sent successfully, False otherwise.
    Failures are logged but don't raise exceptions - feedback should still succeed.
    """
    url = _build_matrix_url()
    if not url or not settings.matrix_access_token:
        logger.warning("matrix_not_configured", notification_type="feedback")
        return False

    contact = email if email else "not provided"
    env_emoji, env_name = _env_prefix()
    body = f"{env_emoji} 📬 **New Feedback** [{env_name}]\n\n{message}\n\n**Contact:** {contact}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers=_get_auth_headers(),
                json={
                    "msgtype": "m.text",
                    "body": body,
                    "format": "org.matrix.custom.html",
                    "formatted_body": body.replace("\n", "<br>"),
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("matrix_notification_sent", notification_type="feedback")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "matrix_notification_error",
            notification_type="feedback",
            status_code=e.response.status_code,
        )
        return False
    except httpx.RequestError as e:
        logger.error(
            "matrix_notification_request_error",
            notification_type="feedback",
            error=str(e),
        )
        return False


async def send_error_alert(
    error_type: str,
    message: str,
    *,
    path: str | None = None,
    correlation_id: str | None = None,
    status_code: int | None = None,
    context: dict | None = None,
) -> bool:
    """
    Send error alert to Matrix room.

    Returns True if notification was sent successfully, False otherwise.
    Failures are logged but don't raise exceptions.
    Rate-limited to prevent alert storms (max 1 alert per 30 seconds).
    """
    url = _build_matrix_url()
    if not url or not settings.matrix_access_token:
        logger.debug("matrix_not_configured")
        return False

    if not _should_send_alert():
        logger.info("matrix_alert_rate_limited", error_type=error_type)
        return False

    # Build alert message
    env_emoji, env_name = _env_prefix()
    lines = [
        f"{env_emoji} 🚨 **Server Error Alert** [{env_name}]",
        f"**Environment:** {env_name}",
        f"**Type:** {error_type}",
    ]
    if status_code:
        lines.append(f"**Status:** {status_code}")
    if path:
        lines.append(f"**Path:** {path}")
    if correlation_id:
        lines.append(f"**Correlation ID:** {correlation_id}")
    if message:
        truncated = message[:500] + "..." if len(message) > 500 else message
        lines.append(f"**Message:** {truncated}")
    if context:
        for key, value in context.items():
            str_value = str(value)
            truncated = str_value[:200] + "..." if len(str_value) > 200 else str_value
            lines.append(f"**{key}:** {truncated}")
    lines.append(f"**Time:** {datetime.now(UTC).isoformat()}")

    body = "\n".join(lines)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers=_get_auth_headers(),
                json={
                    "msgtype": "m.text",
                    "body": body,
                    "format": "org.matrix.custom.html",
                    "formatted_body": body.replace("\n", "<br>"),
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("matrix_error_alert_sent", error_type=error_type)
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "matrix_alert_error",
            error_type=error_type,
            status_code=e.response.status_code,
        )
        return False
    except httpx.RequestError as e:
        logger.error(
            "matrix_alert_request_error",
            error_type=error_type,
            error=str(e),
        )
        return False


def send_error_alert_sync(
    error_type: str,
    message: str,
    *,
    path: str | None = None,
    correlation_id: str | None = None,
    status_code: int | None = None,
    context: dict | None = None,
) -> bool:
    """
    Synchronous version of send_error_alert for scheduler jobs.

    Uses httpx synchronously to avoid asyncio.run() complexity.
    """
    url = _build_matrix_url()
    if not url or not settings.matrix_access_token:
        logger.debug("matrix_not_configured")
        return False

    if not _should_send_alert():
        logger.info("matrix_alert_rate_limited", error_type=error_type)
        return False

    # Build alert message
    env_emoji, env_name = _env_prefix()
    lines = [
        f"{env_emoji} 🚨 **Server Error Alert** [{env_name}]",
        f"**Environment:** {env_name}",
        f"**Type:** {error_type}",
    ]
    if status_code:
        lines.append(f"**Status:** {status_code}")
    if path:
        lines.append(f"**Path:** {path}")
    if correlation_id:
        lines.append(f"**Correlation ID:** {correlation_id}")
    if message:
        truncated = message[:500] + "..." if len(message) > 500 else message
        lines.append(f"**Message:** {truncated}")
    if context:
        for key, value in context.items():
            str_value = str(value)
            truncated = str_value[:200] + "..." if len(str_value) > 200 else str_value
            lines.append(f"**{key}:** {truncated}")
    lines.append(f"**Time:** {datetime.now(UTC).isoformat()}")

    body = "\n".join(lines)

    try:
        with httpx.Client() as client:
            response = client.put(
                url,
                headers=_get_auth_headers(),
                json={
                    "msgtype": "m.text",
                    "body": body,
                    "format": "org.matrix.custom.html",
                    "formatted_body": body.replace("\n", "<br>"),
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("matrix_error_alert_sent", error_type=error_type)
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "matrix_alert_error",
            error_type=error_type,
            status_code=e.response.status_code,
        )
        return False
    except httpx.RequestError as e:
        logger.error(
            "matrix_alert_request_error",
            error_type=error_type,
            error=str(e),
        )
        return False
