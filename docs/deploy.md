# Deployment

IEOMD production runs on the shared `platform` droplet managed by the `platform-infra` repository.

This repository builds a single production image (`ghcr.io/richmiles/ieomd-app`) and includes:

- A cheap PR gate (`make check`) on every PR
- An expensive on-demand ephemeral staging gate (DigitalOcean droplet)
- A production promotion workflow that pins `IEOMD_IMAGE_TAG` on the droplet and runs a deterministic deploy

## Architecture

The `platform` droplet runs Docker Compose with shared infrastructure:

- **Caddy** - Reverse proxy handling TLS for all services
- **Postgres** - Shared database (IEOMD gets isolated `ieomd` user + `ieomd_db`)
- **IEOMD app** - Single container (FastAPI serves the built SPA + API)

Traffic flow:
```
Internet → platform Caddy (TLS) → ieomd:8000
```

## Deployment model (production)

1. Build and push `ghcr.io/richmiles/ieomd-app:sha-<short>` via GitHub Actions.
2. Promote to production (pins `IEOMD_IMAGE_TAG=sha-<short>` on the droplet, pulls, migrates, restarts, health-checks).
3. Verify:
   - `https://ieomd.com/healthz`
   - `https://ieomd.com/api/v1/healthz`

### Migrations (production)

Production uses Postgres, so schema changes should be applied as a one-off, serialized step during deployment (run once per release), then roll the application containers.

The exact commands live in `platform-infra` (source of truth). At a high level, the pattern is:

- Pull the new images
- Run `alembic upgrade head` using the backend image as a one-off job
- Restart the running services

## GitHub Actions Workflows

| Workflow | Purpose |
|----------|---------|
| `ci.yml` | Runs tests on PRs |
| `build.yml` | Builds and pushes the production image to GHCR |
| `ephemeral-staging.yml` | Runs ephemeral staging (manual or `/stage` PR comment) |
| `promote-production.yml` | Pins tag and deploys to the prod droplet |
| `generate-token.yml` | Admin utility for capability tokens |

## Ephemeral Staging

For pre-merge testing, use ephemeral staging:

- Manual: trigger `.github/workflows/ephemeral-staging.yml` with `ref=...`
- PR: comment `/stage` on a PR (owner-only)

The workflow provisions a temporary DigitalOcean droplet and runs the fleet runner
against `deploy/pack.toml`, then destroys the droplet when done.

This avoids maintaining a dedicated staging environment.

Notes:

- Required GitHub secrets: `DO_API_TOKEN`, `SPARK_SWARM_API_KEY`, `SPARK_SWARM_DEPLOY_KEY`
- The workflow uses `sslip.io` so the staging URL is reachable without DNS.
- For debugging, set `keep=true`.

## Database

Production uses PostgreSQL on the `platform` droplet. The database and credentials are managed by platform-infra (source of truth).

## Object Storage

Encrypted file attachments use DigitalOcean Spaces (S3-compatible).

Production uses the shared `platform-storage` bucket with `ieomd/` prefix to isolate objects.

Configuration (in platform-infra `.env`):
- `OBJECT_STORAGE_ENABLED=true`
- `OBJECT_STORAGE_ENDPOINT=https://nyc3.digitaloceanspaces.com`
- `OBJECT_STORAGE_BUCKET=platform-storage`
- `OBJECT_STORAGE_PREFIX=ieomd`

## Local Development

For local development, use:
```bash
make dev          # Run frontend + backend
make minio        # Start local S3-compatible storage (optional)
```

See [README.md](../README.md) for full setup instructions.
