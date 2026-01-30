# Versioning and database migrations

This repository uses a single, repo-wide version and Alembic migrations for schema changes.

## Versioning policy

- Version scheme: Semantic Versioning (SemVer), including pre-release labels when needed (e.g. `0.1.0-beta`).
- Release tags: tag releases as `vX.Y.Z` (or `vX.Y.Z-beta`), matching the repo-wide version.
- Source of truth: keep these files in sync:
  - `backend/pyproject.toml` (`[tool.poetry].version`)
  - `backend/app/main.py` (`FastAPI(..., version=...)`)
  - `frontend/package.json` (`version`)

The frontend UI displays the version subtly in the footer via `__APP_VERSION__`, which is injected at build time from `frontend/package.json` in `frontend/vite.config.ts`.

## Database migrations

### Principles

- Schema changes happen via Alembic migrations only.
- Production migrations should be treated as an explicit, serialized step (run once per release), even if the surrounding deploy process is automated.
- Prefer backwards-compatible changes (expand/contract) so rollbacks don’t require immediate schema reversal.

### Local development (SQLite)

By default the backend uses SQLite via `DATABASE_URL=sqlite:///./secrets.db`.

Run migrations with:

- `make migrate`
- or `cd backend && poetry run alembic upgrade head`

### Ephemeral staging (Postgres)

Ephemeral staging uses Spark Swarm’s fleet runner (`spark-swarm/runner/ephemeral_stage.py`) with `deploy/pack.toml`:

- Provisions a temporary DigitalOcean droplet
- Brings up `postgres` + the app container
- Runs `alembic upgrade head` once
- Runs smoke checks (`/healthz`, `/api/v1/healthz`, `/`)
- Destroys the droplet

### Migration testing

- Migrations are validated by running `alembic upgrade head` against a fresh SQLite database in backend tests.
- Run locally with `make test` or `make check`.

### Production (Postgres)

Production uses Postgres on the shared `platform` droplet. The platform-infra repo is the source of truth for how migrations are applied during deploy.

At a high level:

1. Pull the new images for the release.
2. Run `alembic upgrade head` once as a one-off job using the backend image.
3. Roll/restart the running backend after migrations complete.

### Rollbacks

For production, prefer “roll forward” fixes (new migration + new release). If you must roll back application code, ensure schema changes are backwards-compatible (expand/contract) so the previous image can still run.

## Path to zero downtime (future)

To support zero-downtime releases:

- Use "expand/contract" migrations:
  - Expand: add new nullable columns / new tables first.
  - Deploy code that supports both old and new schema.
  - Contract: remove old columns/constraints in a later release.
- Run migrations as a separate one-off job (only once per release), then roll application instances.
