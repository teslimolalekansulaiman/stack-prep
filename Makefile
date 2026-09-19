SHELL := /bin/bash
# Postgres 18 on macOS refuses to start without a locale (see database/README.md).
export LC_ALL ?= en_US.UTF-8

# Reach the cluster over TCP rather than the Unix socket in .local/run. A socket path is
# capped at 103 bytes, and a git worktree nested under .claude/worktrees/<name> is long
# enough on its own to blow that — so the socket makes the test targets unrunnable from a
# worktree. local-db.sh sets listen_addresses = '127.0.0.1' at initdb, so the port reaches
# the same cluster either way.
DB_HOST ?= 127.0.0.1
DB_PORT ?= 55439

.DEFAULT_GOAL := help

.PHONY: help setup db-start db-stop db-status db-shell migrate db-baseline seed db-test api worker web \
        fixtures test test-py test-js lint format typecheck openapi docker-up docker-down clean

help: ## List the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python and JavaScript dependencies
	uv sync
	npm install

db-start: ## Start the project-local PostgreSQL cluster (port 55439)
	bash database/local-db.sh start

db-stop: ## Stop the project-local PostgreSQL cluster
	bash database/local-db.sh stop

db-status: ## Show cluster status
	bash database/local-db.sh status

db-shell: ## Open psql against the local database
	psql -h $(DB_HOST) -p $(DB_PORT) -d scorepilot

migrate: ## Apply database/migrations in order
	uv run python -m app.cli migrate

db-baseline: ## Record existing migrations as applied (database predates the ledger)
	uv run python -m app.cli baseline

seed: ## Load the reviewed syllabus extraction
	ruby database/load_syllabus.rb

db-test: ## Apply every migration to a disposable database and run the schema tests
	@set -e; \
	db=sp_schema_test; \
	dropdb -h $(DB_HOST) -p $(DB_PORT) --if-exists $$db; \
	createdb -h $(DB_HOST) -p $(DB_PORT) $$db; \
	for f in database/migrations/*.sql database/tests/*.sql; do \
	  echo "  $$f"; \
	  psql -X -q -v ON_ERROR_STOP=1 -h $(DB_HOST) -p $(DB_PORT) -d $$db -f "$$f"; \
	done; \
	dropdb -h $(DB_HOST) -p $(DB_PORT) $$db; \
	echo "Schema tests passed."

API_PORT ?= 8000

api: ## Run the API with reload (override the port with API_PORT=8001)
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port $(API_PORT)

worker: ## Run the background worker (arq)
	uv run arq app.worker.WorkerSettings

web: ## Run the web client at http://127.0.0.1:5173
	npm run dev

fixtures: ## Regenerate engine parity vectors from the Python engine
	uv run python -m engine.fixtures packages/fixtures/vectors.json

test: test-py test-js ## Run every test suite

test-py: ## Run Python tests against a disposable database
	@set -e; \
	db=sp_pytest; \
	dropdb -h $(DB_HOST) -p $(DB_PORT) --if-exists $$db; \
	createdb -h $(DB_HOST) -p $(DB_PORT) $$db; \
	for f in database/migrations/*.sql; do \
	  psql -X -q -v ON_ERROR_STOP=1 -h $(DB_HOST) -p $(DB_PORT) -d $$db -f "$$f" >/dev/null; \
	done; \
	DATABASE_URL="postgresql+asyncpg://$$USER@$(DB_HOST):$(DB_PORT)/$$db" uv run pytest -q; \
	status=$$?; \
	dropdb -h $(DB_HOST) -p $(DB_PORT) $$db; \
	exit $$status

test-js: ## Run JavaScript tests (includes engine parity)
	npm test

lint: ## Lint Python and JavaScript
	uv run ruff check .
	npm run typecheck

format: ## Format Python sources
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Type-check the engine strictly
	uv run mypy packages/engine/src apps/api/src

openapi: ## Regenerate the TypeScript API client from the live schema
	uv run python -m app.cli openapi > packages/api-client/openapi.json
	npx openapi-typescript packages/api-client/openapi.json -o packages/api-client/src/schema.ts

docker-up: ## Optional: run PostgreSQL and Redis in containers instead of natively
	docker compose up -d

docker-down: ## Stop the optional containers
	docker compose down

clean: ## Remove build artefacts and caches
	rm -rf .venv node_modules apps/web/dist .pytest_cache .mypy_cache .ruff_cache
