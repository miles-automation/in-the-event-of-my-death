.PHONY: install backend backend-server frontend dev test migrate lint format format-check typecheck check hooks help
.PHONY: minio minio-down

# Server configuration (override with environment variables for parallel worktrees)
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

help:
	@echo "Available commands:"
	@echo "  make install   - Install all dependencies"
	@echo "  make backend   - Run the backend server"
	@echo "  make frontend  - Run the frontend dev server"
	@echo "  make dev       - Run both backend and frontend (with migrations)"
	@echo "  make test      - Run all tests (backend + frontend)"
	@echo "  make lint      - Run lint checks"
	@echo "  make format    - Auto-format code"
	@echo "  make typecheck - Run TypeScript type checking"
	@echo "  make check     - Run lint, format-check, typecheck, and tests"
	@echo "  make hooks     - Install git hooks"
	@echo "  make migrate   - Run database migrations"

install:
	cd backend && uv sync
	cd frontend && npm install
	@$(MAKE) hooks

# backend-server: internal target without migrate (called by dev after migrate runs once)
backend-server:
	cd backend && uv run uvicorn app.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

backend: migrate backend-server

frontend:
	cd frontend && npm run dev -- --port $(FRONTEND_PORT)

dev: migrate
	@if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \
		$(MAKE) minio; \
	else \
		echo "Skipping MinIO (Docker not installed or not running)"; \
	fi
	@echo "Starting backend and frontend..."
	@echo "Backend: http://localhost:$(BACKEND_PORT)"
	@echo "Frontend: http://localhost:$(FRONTEND_PORT)"
	@echo ""
	@$(MAKE) -j2 backend-server frontend

minio:
	docker compose up -d minio minio-init

minio-down:
	docker compose down

test:
	cd backend && uv run pytest tests/ -v
	cd frontend && npm run test -- --run

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format .
	cd frontend && npm run format:write

format-check:
	cd backend && uv run ruff format --check .
	cd frontend && npm run format

typecheck:
	# Use project references so the app config is actually typechecked
	cd frontend && npx tsc -b

check: lint format-check typecheck test

hooks:
	git config core.hooksPath .githooks

migrate:
	cd backend && uv run alembic upgrade head
