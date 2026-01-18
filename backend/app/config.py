from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str = "sqlite:///./secrets.db"

    # Limits
    max_ciphertext_size: int = 1_000_000  # 1MB
    max_attachment_size_bytes: int = 50_000_000  # 50MB per attachment
    max_unlock_days: int = 730  # 2 years
    min_unlock_minutes: int = 0
    max_expiry_days: int = 1825  # 5 years
    min_expiry_gap_minutes: int = 15  # minimum gap between unlock_at and expires_at

    # Proof of Work
    pow_base_difficulty: int = 18  # ~1-2 sec on modern CPU
    pow_challenge_ttl_seconds: int = 300  # 5 minutes

    # Rate Limiting
    rate_limit_challenges: str = "10/minute"
    rate_limit_creates: str = "5/minute"
    rate_limit_retrieves: str = "30/minute"

    # Cleanup Scheduler
    cleanup_interval_hours: int = 1

    # CORS
    # Set as JSON array via environment variable
    # e.g., CORS_ORIGINS='["https://ieomd.com"]'
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Logging
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    log_format: str = "console"  # "console" or "json"

    # Discord Webhooks
    discord_feedback_webhook_url: str | None = None
    discord_alerts_webhook_url: str | None = None

    # Rate Limiting - Feedback
    rate_limit_feedback: str = "5/minute"

    # Capability Tokens
    capability_tiers: dict = {
        "basic": {
            "max_file_size_bytes": 10_000_000,
            "max_expiry_days": 365,
            "price_sats": 1000,
        },
        "standard": {
            "max_file_size_bytes": 100_000_000,
            "max_expiry_days": 730,
            "price_sats": 5000,
        },
        "large": {
            "max_file_size_bytes": 500_000_000,
            "max_expiry_days": 1825,
            "price_sats": 20000,
        },
    }
    rate_limit_token_create: str = "100/minute"
    rate_limit_token_validate: str = "60/minute"
    internal_api_key: str | None = None

    # Object Storage (S3-compatible; e.g. DigitalOcean Spaces, MinIO)
    object_storage_enabled: bool = False
    object_storage_endpoint: str | None = None
    object_storage_bucket: str | None = None
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None
    object_storage_region: str = "us-east-1"


settings = Settings()
