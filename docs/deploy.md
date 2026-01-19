# Deployment

IEOMD production runs on the shared `platform` droplet managed by the [platform-infra](https://github.com/richmiles/platform-infra) repository.

This repository is responsible for building the IEOMD application images (backend + web). It also contains an “ephemeral staging” workflow that can spin up a short-lived droplet to validate a ref before merging.

## Architecture

The `platform` droplet runs Docker Compose with shared infrastructure:
- **Caddy** - Reverse proxy handling TLS for all services
- **Postgres** - Shared database (IEOMD gets isolated `ieomd` user + `ieomd_db`)
- **IEOMD web** - Frontend + internal Caddy (routes `/api/*` to backend)
- **IEOMD backend** - FastAPI application

Traffic flow:
```
Internet → platform Caddy (TLS) → ieomd:80 (internal Caddy) → backend:8000
```

## Deployment Model

1. **Build images**: Run the `Build` workflow in GitHub Actions (or push to main)
   - Builds `ghcr.io/richmiles/in-the-event-of-my-death-backend:sha-xxxxx`
   - Builds `ghcr.io/richmiles/in-the-event-of-my-death-web:sha-xxxxx`
   - Also tags as `latest`

2. **Deploy**: Update platform-infra and restart services
   ```bash
   ssh root@<platform-ip>
   cd /opt/platform
   # Update image tag in .env
   sed -i 's/IEOMD_IMAGE_TAG=.*/IEOMD_IMAGE_TAG=sha-xxxxx/' .env
   docker compose pull
   docker compose up -d
   ```

3. **Verify**: Check health endpoint
   ```bash
   curl https://ieomd.com/health
   ```

### Migrations (production)

Production uses Postgres, so schema changes should be applied as a one-off, serialized step during deployment (run once per release), then roll the application containers.

The exact commands live in platform-infra (source of truth). At a high level, the pattern is:

- Pull the new images
- Run `alembic upgrade head` using the backend image as a one-off job
- Restart the running services

## GitHub Actions Workflows

| Workflow | Purpose |
|----------|---------|
| `ci.yml` | Runs tests on PRs |
| `build.yml` | Builds and pushes Docker images to GHCR |
| `ephemeral-staging.yml` | Creates temporary staging droplet for testing |
| `cleanup-ephemeral-staging.yml` | Cleans up old ephemeral droplets |
| `generate-token.yml` | Admin utility for capability tokens |

## Ephemeral Staging

For pre-merge testing, use the ephemeral staging workflow:

1. Trigger `.github/workflows/ephemeral-staging.yml` via workflow dispatch
2. It creates a temporary DigitalOcean droplet
3. Deploys using `deploy/docker-compose.yml` and `deploy/remote/ieomd-deploy`, then runs smoke tests
4. Destroys the droplet when done

This avoids maintaining a dedicated staging environment.

Notes:
- Required GitHub secret: `DO_API_TOKEN` (DigitalOcean API token).
- The workflow uses `sslip.io` so the staging URL is reachable without DNS; it prints the URL in the workflow summary.
- For debugging, set `destroy_when_done=false`; the workflow uploads an SSH key as a short-lived artifact.

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
