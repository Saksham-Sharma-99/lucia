.DEFAULT_GOAL := help
.PHONY: help setup env db-up db-down db-reset migrate migration seed e2e dev dev-api dev-worker dev-beat dev-web \
        lint fmt typecheck test eval-drafter gen-client ci

BE := cd backend &&
FE := cd frontend &&

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: env ## Install deps and git hooks
	$(BE) uv sync
	$(FE) pnpm install
	pre-commit install

env: ## Create .env files from examples if missing
	@test -f backend/.env || cp backend/.env.example backend/.env
	@test -f frontend/.env || cp frontend/.env.example frontend/.env
	@grep -q '^SECRET_KEY=.\+' backend/.env || { \
		key=$$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'); \
		grep -v '^SECRET_KEY=' backend/.env > backend/.env.tmp; echo "SECRET_KEY=$$key" >> backend/.env.tmp; \
		mv backend/.env.tmp backend/.env; echo "Generated SECRET_KEY in backend/.env"; }

db-up: ## Start Postgres and Redis
	docker compose up -d --wait

db-down: ## Stop Postgres and Redis
	docker compose down

db-reset: ## Drop volumes and start fresh
	docker compose down -v && docker compose up -d --wait

migrate: ## Apply migrations
	$(BE) uv run alembic upgrade head

seed: ## Seed users, firms, templates and the runtime demo (idempotent)
	$(BE) uv run python -m lucia.seeds

migration: ## Create a migration: make migration m="add agents"
	$(BE) uv run alembic revision --autogenerate -m "$(m)"

dev: ## Run API, worker, beat and web together (Ctrl-C stops all)
	$(MAKE) -j4 dev-api dev-worker dev-beat dev-web

dev-api: ## FastAPI on :8000 (restarts on code or .env changes)
	$(BE) uv run uvicorn lucia.main:app --reload --reload-include .env --port 8000

# Celery has no reload of its own; watchfiles (shipped with uvicorn[standard]) restarts it.
WATCH := uv run watchfiles --filter default

dev-worker: ## Celery worker, restarts on code or .env changes (threads pool: prefork breaks on macOS spawn)
	$(BE) $(WATCH) "celery -A lucia.worker.celery_app worker --pool=threads --concurrency=8 -Q interactive,episodes,sched,notify,maintenance,celery --loglevel=INFO" src .env

dev-beat: ## Celery beat, restarts on code or .env changes
	$(BE) $(WATCH) "celery -A lucia.worker.celery_app beat --loglevel=INFO" src .env

dev-web: ## Vite on :5173 (proxies /api to :8000)
	$(FE) pnpm dev

lint: ## Lint and format-check both apps
	$(BE) uv run ruff check . && uv run ruff format --check .
	$(FE) pnpm lint && pnpm format:check

fmt: ## Format both apps
	$(BE) uv run ruff check --fix . && uv run ruff format .
	$(FE) pnpm format

typecheck: ## Type-check both apps
	$(BE) uv run pyright
	$(FE) pnpm typecheck

test: ## Run backend and frontend tests (needs make db-up)
	$(BE) uv run pytest
	$(FE) pnpm test

e2e: ## Browser smoke test against a running `make dev` (E2E_PASSWORD=<seed password>); cleans up its data
	$(FE) pnpm e2e

eval-drafter: ## Drafter evals against the real model (needs OPENAI_API_KEY; costs tokens)
	$(BE) uv run python -m evals.drafter.run

eval-orchestrator: ## Orchestrator subject + routing evals against the real model (costs tokens)
	$(BE) uv run python -m evals.orchestrator.run

gen-client: ## Regenerate the TS API client (needs make dev-api running)
	$(FE) pnpm gen:api

ci: lint typecheck test ## Everything CI runs
	$(BE) uv run alembic upgrade head && uv run alembic check
	$(FE) pnpm build
