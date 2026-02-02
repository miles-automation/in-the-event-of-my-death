# AGENTS.md - Instructions for coding agents

This repo is a small monorepo:
- `frontend/`: React 19 + TypeScript + Vite
- `backend/`: FastAPI + SQLAlchemy + Alembic (SQLite for local dev via `DATABASE_URL`)

## Fleet contract (Spark Swarm standard)

This repo participates in the Spark Swarm “fleet” standard for staging and production deploys.

### Health (required)
- `GET /healthz` (public, DB-checked)
- `GET /api/v1/healthz` (DB-checked; verifies proxy routing)
- Legacy: `GET /health` (optional)

### Ephemeral staging (required)
- Deploy definition: `deploy/pack.toml` (`database.kind="postgres"`)
- GitHub Action: `Ephemeral Staging` (manual or `/stage` PR comment; owner-only)

### Production promotion (required)
- GitHub Action: `Promote to Production`
- Pins: `IEOMD_IMAGE_TAG=sha-...` on the prod droplet and restarts service `ieomd`
- Health URL: `https://ieomd.com/healthz`

### Image + secrets
- Image: `ghcr.io/richmiles/ieomd-app:<tag>`
- Secrets source: Spark Swarm secrets export
  - Staging: `project=ieomd environment=staging`
  - Production: `project=ieomd environment=production` (mirrored into `/root/platform-infra/.env`)
- Required secrets: `IEOMD_DB_PASSWORD`
- Workflow secrets (GitHub): `DO_API_TOKEN`, `SPARK_SWARM_API_KEY`, `SPARK_SWARM_DEPLOY_KEY`, `PROD_SSH_KEY`

## Before Starting Work (REQUIRED)
**STOP: Do not write any code until these steps are complete.**

1. **Verify a GitHub issue exists** for the task
   - If no issue exists, create one: `gh issue create --title "<title>" --body "<description>"`
   - Every change must trace back to an issue

2. **Link the issue to the appropriate GitHub project**
   - `gh project item-add <project-number> --owner richmiles --url <issue-url>`
   - Active projects:
     - **#8** - IEOMD v0.2 - Payment Infrastructure (capability tokens, Lightning)
     - **#9** - IEOMD v0.3 - Premium Features (file uploads, edit content)
     - **#11** - IEOMD - UX Enhancements (link ordering, defaults, sharing)
     - **#12** - IEOMD - Infrastructure (ongoing DevOps, monitoring, tooling)

3. **Create a dedicated branch + worktree for the issue**
   - This is required for ALL work (including small docs changes), not just parallel work
   - All work must be done inside the issue worktree (not the main checkout)
   ```bash
   git fetch origin
   git worktree add ../ieomd-<issue-number> -b <type>/<issue-number>-<short-description> origin/main
   cd ../ieomd-<issue-number>
   make install
   ```
   - Run `make install` once per worktree (each worktree has its own `node_modules` and Poetry virtualenv)
   - Example: `git worktree add ../ieomd-64 -b feature/64-file-uploads`
   - Use `feature/`, `fix/`, or `docs/` prefix per branch naming rules below
   - If the branch already exists, create a worktree from it: `git worktree add ../ieomd-<issue-number> <branch-name>`
   - If already in the correct issue worktree, proceed without creating a new one

**If the user requests work without an issue number, ask them to confirm issue creation before proceeding.**

## Day-to-day commands (prefer Make)
- Install deps: `make install`
- Run dev: `make dev` (backend `:8000`, frontend `:5173`)
- Migrations: `make migrate`
- Tests: `make test`
- Lint/format/typecheck: `make lint`, `make format`, `make typecheck`
- Checks (must pass before PR): `make check`

## Repository conventions
- Frontend pages live in `frontend/src/pages/` and should follow existing component patterns.
- Backend layering is `routers/` → `services/` → `models/` (+ `schemas/` for Pydantic).
- Add/update tests for new behavior:
  - Backend: `backend/tests/` (unit + integration style tests)
  - Frontend: `vitest` via `npm run test` (wired through `make test`)
- Do not leave `console.log` / `print` debugging in commits.

## Security / privacy invariants (do not violate)
- Zero-knowledge: encryption/decryption happens client-side; never send keys or plaintext to the server.
- Decryption keys are carried in the URL fragment; the server must never need or log them.
- Avoid logging sensitive request bodies or ciphertext; keep telemetry minimal.
- Be conservative changing cryptography (`frontend/src/services/crypto.ts`); prefer small, well-reviewed edits with tests.

## Branch + commit expectations (when doing repo work)
- Branch naming:
  - Feature: `feature/<issue-number>-short-description`
  - Fix: `fix/<issue-number>-short-description`
  - Docs: `docs/<description>`
- Commit messages: `<type>: <description>` (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`)
- PRs should reference the issue (e.g., "Closes #123") and `make check` must pass.

## After PR is Merged (REQUIRED)
Clean up the worktree and branch:
```bash
cd /path/to/main/repo
git worktree remove ../ieomd-<issue-number>
git branch -d <type>/<issue-number>-<short-description>
git worktree prune
```

## When adding dependencies
Avoid new dependencies unless necessary; prefer built-ins and existing libs. If a new dependency is required, explain why and update lockfiles (`backend/poetry.lock` or `frontend/package-lock.json`) intentionally.

## Available CLI Tools
These CLIs are authenticated and available:
- **`gh`** - GitHub CLI for issues, PRs, workflows, projects, and API calls
- **`doctl`** - DigitalOcean CLI for droplet management and infrastructure
- **`ssh`** - Direct server access via `ssh root@<ip>` (root is intentional; get IPs from `doctl compute droplet list`)

## Posting PR Review Notes via `gh`
When leaving review feedback with `gh pr review`, prefer `--body-file` to avoid shell interpolation/escaping issues (especially with backticks, `$VARS`, or code blocks).

```bash
tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT
cat > "$tmpfile" <<'EOF'
Summary:
- Looks good overall

Requested changes:
- Please add a test for the new edge case
EOF

gh pr review 123 --comment --body-file "$tmpfile"
# or:
gh pr review 123 --request-changes --body-file "$tmpfile"
gh pr review 123 --approve --body-file "$tmpfile"
```

---

## Running Multiple Dev Servers

When working on multiple issues in parallel, each worktree needs different ports:

| Worktree | Frontend | Backend | Command |
|----------|----------|---------|---------|
| First | 5173 | 8000 | `make dev` |
| Second | 5174 | 8001 | `FRONTEND_PORT=5174 BACKEND_PORT=8001 make dev` |
| Third | 5175 | 8002 | `FRONTEND_PORT=5175 BACKEND_PORT=8002 make dev` |

## Parallel Work Guidelines

Multiple issues can be worked simultaneously when they touch independent parts of the codebase.

### Subsystem Independence Map

| Subsystem | Key Files | Safe to Parallelize With |
|-----------|-----------|--------------------------|
| Frontend UI | `frontend/src/pages/*`, `frontend/src/components/*` | Backend API, Database |
| Frontend Services | `frontend/src/services/*` | Backend (if API unchanged) |
| Backend API | `backend/app/routers/*` | Frontend (if contracts stable) |
| Backend Services | `backend/app/services/*` | Frontend, Database migrations |
| Database | `backend/app/models/*`, `backend/alembic/*` | Frontend |
| Infrastructure | `Makefile`, `docker-compose.yml` | Nothing (serialize these) |
| Docs | `docs/*`, `*.md` | Everything |

### Coordination

- **Check for conflicts before starting** - Review which files each issue will touch
- **Merge sequentially** - Don't merge PRs simultaneously; let CI run between merges
- **Rebase after conflicts** - If main updates, rebase your branch before continuing

**Note:** Each worktree has its own SQLite database (relative path `sqlite:///./secrets.db`), so parallel worktrees won't conflict on data.
