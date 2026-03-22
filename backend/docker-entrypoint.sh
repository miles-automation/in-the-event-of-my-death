#!/usr/bin/env bash
set -euo pipefail

# Run migrations
alembic upgrade head

# Start server
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
