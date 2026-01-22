import secrets as secrets_module
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy import inspect

from app.config import settings
from app.database import engine
from app.logging_config import get_logger, setup_logging
from app.middleware.logging import LoggingMiddleware
from app.middleware.rate_limit import limiter
from app.routers import (
    attachments,
    btcpay_webhook,
    capability_tokens,
    challenges,
    feedback,
    secrets,
)
from app.scheduler import shutdown_scheduler, start_scheduler
from app.services.matrix_service import send_error_alert

# Initialize logging before anything else
setup_logging()
logger = get_logger("app")

# Database tables are managed by Alembic migrations
# Run: poetry run alembic upgrade head


def check_database_tables():
    """
    Check that required database tables exist.

    Raises RuntimeError with helpful message if tables are missing.
    This helps catch the case where migrations haven't been run.
    """
    required_tables = {"secrets", "pow_challenges", "capability_tokens"}
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    missing_tables = required_tables - existing_tables
    if missing_tables:
        raise RuntimeError(
            f"Database tables missing: {missing_tables}. "
            "Please run database migrations first: make migrate "
            "(or: cd backend && poetry run alembic upgrade head)"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - start/stop scheduler."""
    check_database_tables()
    logger.info("app_starting", version="0.1.0-beta")
    start_scheduler()
    yield
    logger.info("app_stopping")
    shutdown_scheduler()


app = FastAPI(
    title="InTheEventOfMyDeath",
    description="Zero-knowledge time-locked secret delivery service",
    version="0.1.0-beta",
    lifespan=lifespan,
)


# Exception handler to add correlation ID to all error responses
@app.exception_handler(Exception)
async def add_correlation_id_to_errors(request: Request, exc: Exception):
    """
    Catch-all exception handler that ensures X-Correlation-ID is included in error responses.

    This handler preserves HTTPException status codes and details,
    and returns 500 for all other exceptions.

    The correlation ID should always be available from the LoggingMiddleware context.
    If it's somehow missing, we generate a fallback ID and log a warning.
    """
    # Get correlation ID from structlog context
    contextvars = structlog.contextvars.get_contextvars()
    correlation_id = contextvars.get("correlation_id")

    # Fallback if correlation ID is missing (shouldn't happen with proper middleware order)
    if correlation_id is None:
        correlation_id = secrets_module.token_hex(4)
        logger.warning(
            "correlation_id_missing_in_exception_handler",
            path=request.url.path,
            method=request.method,
            fallback_id=correlation_id,
        )

    # Preserve HTTPException details and headers
    if isinstance(exc, HTTPException):
        # Alert on 5xx HTTPExceptions
        if exc.status_code >= 500:
            await send_error_alert(
                error_type="HTTPException",
                message=str(exc.detail),
                path=request.url.path,
                correlation_id=correlation_id,
                status_code=exc.status_code,
            )
        headers = dict(exc.headers or {})
        headers["X-Correlation-ID"] = correlation_id
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )

    # For all other exceptions, return 500
    # Alert on unhandled exceptions
    await send_error_alert(
        error_type=type(exc).__name__,
        message=str(exc),
        path=request.url.path,
        correlation_id=correlation_id,
        status_code=500,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers={"X-Correlation-ID": correlation_id},
    )


# Rate limiting
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom rate limit handler that sends Matrix alerts."""
    # Get correlation ID from structlog context
    contextvars = structlog.contextvars.get_contextvars()
    correlation_id = contextvars.get("correlation_id")

    await send_error_alert(
        error_type="Rate Limit Exceeded",
        message=str(exc.detail),
        path=request.url.path,
        correlation_id=correlation_id,
        status_code=429,
    )
    return JSONResponse(
        status_code=429,
        content={"detail": str(exc.detail)},
        headers={"Retry-After": "60", "X-Correlation-ID": correlation_id or ""},
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging
app.add_middleware(LoggingMiddleware)

# Routers
app.include_router(attachments.router, prefix="/api/v1", tags=["attachments"])
app.include_router(capability_tokens.router, prefix="/api/v1", tags=["capability-tokens"])
app.include_router(challenges.router, prefix="/api/v1", tags=["challenges"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
app.include_router(secrets.router, prefix="/api/v1", tags=["secrets"])
app.include_router(btcpay_webhook.router, prefix="/api/v1", tags=["btcpay"])


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Static file serving for production (when frontend is built into ./static)
STATIC_DIR = Path(__file__).parent.parent / "static"

if STATIC_DIR.exists():
    # Serve static assets (js, css, images, etc.)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    # SPA catch-all: serve index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes."""
        # Don't intercept API routes or health check
        if full_path.startswith("api/") or full_path == "health":
            raise HTTPException(status_code=404, detail="Not found")

        # Serve static file if it exists
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # Otherwise serve index.html for client-side routing
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Not found")
