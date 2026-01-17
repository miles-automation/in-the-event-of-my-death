"""Background scheduler for periodic cleanup tasks."""

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.discord_service import send_error_alert_sync
from app.services.pow_service import cleanup_expired_challenges
from app.services.secret_service import clear_expired_secrets
from app.services.storage_service import ObjectStorageService

logger = get_logger("scheduler")

scheduler = BackgroundScheduler()


async def _delete_storage_blobs(storage_keys: list[str]) -> int:
    """Delete blobs from object storage. Returns count of deleted blobs."""
    if not storage_keys:
        return 0

    storage_service = ObjectStorageService(settings)
    deleted = 0

    for key in storage_keys:
        try:
            await storage_service.delete_object(object_key=key)
            deleted += 1
        except Exception as e:
            # Log but don't fail the whole job for individual blob failures
            logger.warning("blob_delete_failed", storage_key=key, error=str(e))

    return deleted


def cleanup_secrets_job() -> None:
    """Run periodic cleanup of expired and retrieved secrets."""
    db = SessionLocal()
    try:
        cleared, storage_keys = clear_expired_secrets(db)

        # Delete blobs from object storage if any
        deleted_blobs = 0
        if storage_keys and settings.object_storage_enabled:
            try:
                deleted_blobs = asyncio.run(_delete_storage_blobs(storage_keys))
            except Exception as e:
                logger.error("blob_cleanup_failed", error=str(e), key_count=len(storage_keys))

        logger.info(
            "cleanup_secrets_completed",
            cleared_count=cleared,
            deleted_blobs=deleted_blobs,
        )
    except Exception as e:
        logger.error("cleanup_secrets_failed", error=str(e))
        send_error_alert_sync(
            error_type="Scheduler Job Failed",
            message=str(e),
            context={"job_name": "cleanup_secrets"},
        )
    finally:
        db.close()


def cleanup_challenges_job() -> None:
    """Run periodic cleanup of expired PoW challenges."""
    db = SessionLocal()
    try:
        deleted = cleanup_expired_challenges(db)
        logger.info("cleanup_challenges_completed", deleted_count=deleted)
    except Exception as e:
        logger.error("cleanup_challenges_failed", error=str(e))
        send_error_alert_sync(
            error_type="Scheduler Job Failed",
            message=str(e),
            context={"job_name": "cleanup_challenges"},
        )
    finally:
        db.close()


def start_scheduler() -> None:
    """Start the background scheduler."""
    scheduler.add_job(
        cleanup_secrets_job,
        trigger=IntervalTrigger(hours=settings.cleanup_interval_hours),
        id="cleanup_expired_secrets",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_challenges_job,
        trigger=IntervalTrigger(hours=settings.cleanup_interval_hours),
        id="cleanup_expired_challenges",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler_started", cleanup_interval_hours=settings.cleanup_interval_hours)


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    scheduler.shutdown()
    logger.info("scheduler_stopped")
