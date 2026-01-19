# CLAUDE.md - Project Instructions for Claude Code

## Project Overview
"In The Event Of My Death" - A zero-knowledge, time-locked secret delivery service.
- Frontend: React 19 + TypeScript + Vite
- Backend: Python FastAPI + SQLAlchemy + SQLite
- Encryption: AES-256-GCM (client-side)

## Development Commands
- `make dev` - Run both frontend and backend
- `make test` - Run all tests (backend + frontend)
- `make lint` - Lint both frontend and backend
- `make format` - Format code
- `make typecheck` - TypeScript type checking
- `make check` - Run all checks (lint, format, typecheck, test)

## Architecture Notes
- Zero-knowledge: encryption keys are never sent to server (stored in URL fragment)
- Secrets have `unlock_at` (when viewable) and `expires_at` (when auto-deleted)
- Proof-of-work protects against spam

## Key Files
- `frontend/src/pages/Home.tsx` - Main secret creation form
- `frontend/src/services/crypto.ts` - Client-side encryption
- `backend/app/models/secret.py` - Secret database model
- `backend/app/services/secret_service.py` - Secret business logic

## Code Conventions
- Use existing patterns when adding features
- Keep page components in `frontend/src/pages/`
- Backend follows FastAPI patterns: routers → services → models
- Run `make check` before committing

## Environment Variables
- Frontend: `VITE_API_URL`, `VITE_BASE_URL`
- Backend: `DATABASE_URL`, `CORS_ORIGINS`

## Docker

Build and run locally:

```bash
# Build the image
docker build -t ieomd .

# Run with SQLite (ephemeral)
docker run -p 8000:8000 ieomd

# Run with Postgres
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/ieomd_db \
  -e CORS_ORIGINS='["https://ieomd.com"]' \
  ieomd
```

The container:
- Builds the frontend and serves it from FastAPI
- Exposes port 8000 (both API and frontend)
- Runs database migrations on startup
- Accepts `DATABASE_URL` for Postgres (defaults to SQLite)

## Available CLI Tools
Claude has authenticated access to these CLIs for infrastructure and repo management:

- **`gh`** - GitHub CLI (authenticated)
  - Issues: `gh issue list`, `gh issue create`, `gh issue view <issue-number>`
  - PRs: `gh pr create`, `gh pr list`, `gh pr view <pr-number>`
  - PR reviews: see “Posting PR Review Notes via `gh`” below
  - Workflows: `gh workflow run <name>`, `gh run list`, `gh run view <run-id>`
  - Projects: `gh project item-add <project-number> --owner richmiles --url <issue-url>`
  - API: `gh api <endpoint>` for any GitHub API call

- **`doctl`** - DigitalOcean CLI (authenticated)
  - Droplets: `doctl compute droplet list`
  - Droplet name: `platform` (shared infra - runs IEOMD production)

- **`ssh`** - Direct server access
  - `ssh root@<ip>` (root access is intentional for this setup)
  - Get IPs via `doctl compute droplet list`

---

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

## Workflow

### Before Starting Work (REQUIRED)
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

3. **Create a worktree for the issue**
   ```bash
   git fetch origin
   git worktree add ../ieomd-<issue-number> -b <type>/<issue-number>-<short-description> origin/main
   cd ../ieomd-<issue-number>
   make install
   ```
   - Run `make install` once per worktree (each worktree has its own `node_modules` and Poetry virtualenv)
   - Example: `git worktree add ../ieomd-64 -b feature/64-file-uploads`
   - Use `feature/`, `fix/`, or `docs/` prefix per branch naming rules below
   - This is required for ALL work (including small docs changes), not just parallel work
   - All work must be done inside the issue worktree (not the main checkout)
   - If the branch already exists, create a worktree from it: `git worktree add ../ieomd-<issue-number> <branch-name>`
   - If already in the correct issue worktree, proceed without creating a new one

**If the user requests work without an issue number, ask them to confirm issue creation before proceeding.**

### Branch Naming
- Feature: `feature/<issue-number>-short-description` (e.g., `feature/5-expiry-backend`)
- Fix: `fix/<issue-number>-short-description`
- Docs: `docs/<description>`

### Commit Messages
Format: `<type>: <description>`

Types:
- `feat` - New feature
- `fix` - Bug fix
- `refactor` - Code refactoring
- `docs` - Documentation
- `test` - Adding/updating tests
- `chore` - Maintenance tasks

Example: `feat: add expires_at column to secrets model`

### Pull Request Process
1. Work in the issue's worktree (created in step 3 above)
2. Make changes, commit with conventional messages
3. Run `make check` - all checks must pass
4. Push and create PR referencing the issue: "Closes #5"
5. PR title should match the issue title

### After PR is Merged (REQUIRED)
Clean up the worktree and branch:
```bash
cd /path/to/main/repo
git worktree remove ../ieomd-<issue-number>
git branch -d <type>/<issue-number>-<short-description>
git worktree prune
```

### Testing Requirements
- Backend: Add/update tests in `backend/tests/` for any new functionality
- Run `make test` before submitting PR
- New API endpoints need integration tests
- New service functions need unit tests

### Before Submitting
Checklist:
- [ ] `make check` passes
- [ ] Tests added/updated for new functionality
- [ ] No console.log or print statements left in code
- [ ] Environment variables documented if added

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

**Safe to parallelize:**
- Frontend UI vs Backend API
- Independent features in different files
- Documentation alongside any code work

**Avoid parallelizing:**
- Issues that modify the same files
- Tasks that depend on each other's changes
- Changes to shared config (package.json, pyproject.toml, Makefile)

**Note:** Each worktree has its own SQLite database (relative path `sqlite:///./secrets.db`), so parallel worktrees won't conflict on data.
