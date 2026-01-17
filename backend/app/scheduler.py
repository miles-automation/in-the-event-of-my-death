"""Background scheduler for periodic cleanup tasks."""

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.attachment_service import delete_orphaned_attachments
from app.services.discord_service import send_error_alert_sync
from app.services.pow_service import cleanup_expired_challenges
from app.services.secret_service import (
    clear_secret_and_attachments,
    get_secrets_needing_cleanup,
)
from app.services.storage_service import ObjectStorageService

logger = get_logger("scheduler")

scheduler = BackgroundScheduler()


def _truncate_key(key: str, length: int = 8) -> str:
    """Truncate storage key for safe logging."""
    if len(key) <= length:
        return key
    return f"{key[:length]}..."


async def _delete_storage_blobs(storage_keys: list[str]) -> tuple[list[str], list[str]]:
    """
    Delete blobs from object storage.

    Returns (succeeded_keys, failed_keys) so caller can handle partial failures.
    """
    if not storage_keys:
        return [], []

    storage_service = ObjectStorageService(settings)
    succeeded: list[str] = []
    failed: list[str] = []

    for key in storage_keys:
        try:
            await storage_service.delete_object(object_key=key)
            succeeded.append(key)
        except Exception as e:
            failed.append(key)
            logger.warning(
                "blob_delete_failed",
                storage_key_prefix=_truncate_key(key),
                error=str(e),
            )

    return succeeded, failed


def cleanup_secrets_job() -> None:
    """
    Run periodic cleanup of expired and retrieved secrets.

    For each secret needing cleanup:
    1. If it has attachments, delete the S3 blobs first
    2. Only if all blobs are deleted, clear the secret and delete attachment rows
    3. Secrets with failed blob deletions are left uncleared for retry next run
    """
    db = SessionLocal()
    try:
        secrets_to_cleanup = get_secrets_needing_cleanup(db)

        cleared_count = 0
        deleted_blobs = 0
        skipped_count = 0

        for secret_id, storage_keys in secrets_to_cleanup:
            # If secret has attachments, delete blobs first
            if storage_keys:
                if settings.object_storage_enabled:
                    try:
                        succeeded, failed = asyncio.run(_delete_storage_blobs(storage_keys))
                        deleted_blobs += len(succeeded)

                        # Only clear if ALL blobs were deleted
                        if failed:
                            logger.warning(
                                "secret_cleanup_skipped",
                                secret_id=secret_id,
                                failed_blobs=len(failed),
                                reason="blob_deletion_failed",
                            )
                            skipped_count += 1
                            continue
                    except Exception as e:
                        logger.error(
                            "blob_cleanup_failed",
                            secret_id=secret_id,
                            error=str(e),
                        )
                        skipped_count += 1
                        continue
                else:
                    # Object storage not enabled but secret has attachments
                    # This shouldn't happen, but skip to avoid orphaned rows
                    logger.warning(
                        "secret_cleanup_skipped",
                        secret_id=secret_id,
                        reason="object_storage_disabled_but_has_attachments",
                    )
                    skipped_count += 1
                    continue

            # All blobs deleted (or no attachments), clear the secret
            if clear_secret_and_attachments(db, secret_id):
                cleared_count += 1

        logger.info(
            "cleanup_secrets_completed",
            cleared_count=cleared_count,
            deleted_blobs=deleted_blobs,
            skipped_count=skipped_count,
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


def cleanup_orphaned_attachments_job() -> None:
    """
    Run periodic cleanup of orphaned attachments.

    Orphaned attachments are those uploaded but never linked to a secret.
    This can happen if a user uploads files but doesn't complete secret creation.
    """
    if not settings.object_storage_enabled:
        return  # Nothing to clean up if object storage is disabled

    db = SessionLocal()
    try:
        storage_service = ObjectStorageService(settings)
        deleted = asyncio.run(delete_orphaned_attachments(db, storage_service, max_age_hours=24))
        if deleted > 0:
            logger.info("cleanup_orphaned_attachments_completed", deleted_count=deleted)
    except Exception as e:
        logger.error("cleanup_orphaned_attachments_failed", error=str(e))
        send_error_alert_sync(
            error_type="Scheduler Job Failed",
            message=str(e),
            context={"job_name": "cleanup_orphaned_attachments"},
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
    scheduler.add_job(
        cleanup_orphaned_attachments_job,
        trigger=IntervalTrigger(hours=settings.cleanup_interval_hours),
        id="cleanup_orphaned_attachments",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler_started", cleanup_interval_hours=settings.cleanup_interval_hours)


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    scheduler.shutdown()
    logger.info("scheduler_stopped")
