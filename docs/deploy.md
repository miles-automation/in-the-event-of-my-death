# Deployment (DigitalOcean droplet)

This document describes deployment setup using DigitalOcean infrastructure.

Goals:
- Automated deployments via GitHub Actions
- PostgreSQL on shared platform infrastructure (SQLite still supported for local dev)
- Shared object storage (DigitalOcean Spaces) with project prefix
- Locked-down deploy access (least privilege)

## Shared Platform Infrastructure

Production IEOMD runs on the shared `platform` droplet managed by [`richmiles/platform-infra`](https://github.com/richmiles/platform-infra).

The platform provides:
- **Postgres** - Shared database server (each service gets its own database)
- **Caddy** - Reverse proxy with automatic HTTPS
- **DigitalOcean Spaces** - Shared S3-compatible object storage (`platform-storage` bucket)

IEOMD-specific configuration in platform-infra:
- Service: `ieomd` (pulls `ghcr.io/richmiles/ieomd:latest`)
- Database: `ieomd_db` with user `ieomd`
- Object storage prefix: `ieomd/` (isolates IEOMD objects in shared bucket)
- Caddy routes: `ieomd.com` → `ieomd:8000`

To deploy or update IEOMD on platform, see the [platform-infra README](https://github.com/richmiles/platform-infra).

## Standalone Architecture (Legacy/Staging)

For standalone deployments (e.g., ephemeral staging), IEOMD can run on its own droplet:

- **Droplet** runs Docker Compose:
  - `web` (Caddy + frontend static assets)
  - `backend` (FastAPI)
- **Caddy** terminates TLS and reverse-proxies:
  - `/api/*` and `/health` → backend
  - everything else → frontend static files with SPA fallback

Compose files live in `deploy/`.

## One-time droplet setup (prod)

1. Create an Ubuntu LTS droplet.
2. Install Docker + Compose plugin.
3. Create directories:
   - `/opt/ieomd/` (deployment directory)
   - `/var/backups/ieomd/` (database backups, if needed)
4. Copy these files to `/opt/ieomd/`:
   - `deploy/docker-compose.yml`
   - `deploy/docker-compose.staging.yml` (staging only)
   - `deploy/Caddyfile` (if you want to override baked-in config)
5. Create `/opt/ieomd/.env` with at least:
   - `SITE_HOST=ieomd.com`
   - `SITE_ADDRESS=ieomd.com, www.ieomd.com` (Caddy site label(s))
   - `DATABASE_URL=postgresql://ieomd:<password>@<platform-ip>:5432/ieomd`
6. Ensure `/opt/ieomd` contains a compose override if needed.

## Locked-down deploy user

Recommended approach:
- Create a `deploy` user that cannot open an interactive shell.
- Install the deploy script as root: `/usr/local/bin/ieomd-deploy` from `deploy/remote/ieomd-deploy`.
- In `authorized_keys`, force the command to run `sudo /usr/local/bin/ieomd-deploy ...` and disable PTY/port-forwarding.
- In sudoers, allow only that command for the deploy user.

## GitHub Actions secrets

You’ll need repository secrets for production, and for ephemeral staging (recommended).

- `DO_API_TOKEN` (DigitalOcean API token; required for ephemeral staging workflows)
- Legacy always-on staging droplet (optional):
  - `STAGING_SSH_HOST`, `STAGING_SSH_USER`, `STAGING_SSH_KEY`, `STAGING_SSH_KNOWN_HOSTS`
  - `STAGING_SITE_HOST` (e.g. `staging.ieomd.com`)
- `PROD_SSH_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY`, `PROD_SSH_KNOWN_HOSTS`
- `PROD_SITE_HOST` (e.g. `ieomd.com`)

## GHCR image pulls

The droplet must be able to pull images from GHCR:

- Easiest: make the GHCR packages public.
- If packages are private: authenticate on the droplet (one-time):
  - Create a GitHub token with `read:packages`
  - On the droplet: `docker login ghcr.io`

## Deployment workflows

- Ephemeral staging deploy is manual (workflow dispatch) and should be destroyed after use:
  - `.github/workflows/ephemeral-staging.yml`
  - Backstop cleanup: `.github/workflows/cleanup-ephemeral-staging.yml`
- Legacy always-on staging droplet deploy is manual:
  - `.github/workflows/build-and-deploy-staging.yml`
- Production deploy is manual and gated by GitHub Environments approval:
  - `.github/workflows/promote-to-production.yml` (version bump + deploy)
  - `.github/workflows/deploy-production.yml` (deploy an existing tag)

## Ephemeral staging (recommended)

For a low-cost staging environment that only runs when needed, use the GitHub Actions workflow:

- `.github/workflows/ephemeral-staging.yml`

It will:
1. Build and push backend/web images tagged with the workflow run.
2. Create a short-lived DigitalOcean droplet (same baseline as prod/staging: Ubuntu 24.04, `s-1vcpu-1gb` in `nyc3`).
3. Deploy using `/usr/local/bin/ieomd-deploy` (includes SQLite backup-before-migrate).
4. Run `scripts/smoke-test.py` against the deployed site.
5. Destroy the droplet (default) and delete the temporary DigitalOcean SSH key.

Notes:
- The workflow uses a temporary hostname `https://<ip>.sslip.io` to avoid managing DNS for ephemeral runs.
- A scheduled backstop cleanup exists in `.github/workflows/cleanup-ephemeral-staging.yml` to delete any stray droplets tagged `ephemeral-staging`.

## Database (PostgreSQL)

Production uses PostgreSQL on the shared `platform` droplet. SQLite is still supported for local development.

### Initial setup (on platform droplet)

```sql
CREATE DATABASE ieomd;
CREATE USER ieomd WITH ENCRYPTED PASSWORD '<secure-password>';
GRANT ALL PRIVILEGES ON DATABASE ieomd TO ieomd;
-- For Alembic migrations
\c ieomd
GRANT ALL ON SCHEMA public TO ieomd;
```

### Environment configuration

In `/opt/ieomd/.env`:
```env
DATABASE_URL=postgresql://ieomd:<password>@<platform-ip>:5432/ieomd
```

### Running migrations

After deploy, run migrations:
```bash
docker compose run --rm backend alembic upgrade head
```

### Rollback plan

For database rollback:
1. Restore from PostgreSQL backup (pg_dump/pg_restore)
2. Redeploy the previous image tag

## Object storage (DigitalOcean Spaces)

For encrypted file attachments, configure an S3-compatible bucket (DigitalOcean Spaces).

Production uses the shared `platform-storage` bucket with a project prefix to isolate IEOMD objects.

1. Ensure access to the shared Spaces bucket (`platform-storage`).
2. Add to `/opt/ieomd/.env`:
   - `OBJECT_STORAGE_ENABLED=true`
   - `OBJECT_STORAGE_ENDPOINT=https://nyc3.digitaloceanspaces.com`
   - `OBJECT_STORAGE_BUCKET=platform-storage`
   - `OBJECT_STORAGE_PREFIX=ieomd`
   - `OBJECT_STORAGE_ACCESS_KEY=<spaces-access-key>`
   - `OBJECT_STORAGE_SECRET_KEY=<spaces-secret-key>`
   - `OBJECT_STORAGE_REGION=nyc3`

The `OBJECT_STORAGE_PREFIX` setting prepends `ieomd/` to all object keys (e.g., `ieomd/attachments/{uuid}`), allowing multiple projects to share the same bucket.
