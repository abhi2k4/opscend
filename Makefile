UV ?= uv

.PHONY: help install dev-api dev-web worker migrate test lint format check check-web check-ai eval eval-memory

help:
	@echo "make install   install api (uv) and web (pnpm) dependencies"
	@echo "make dev-api   API on http://127.0.0.1:8000 (SQLite, inline jobs, demo data)"
	@echo "make dev-web   web app on http://localhost:3000"
	@echo "make worker    arq worker (only when REDIS_URL is set)"
	@echo "make migrate   apply database migrations"
	@echo "make test      run the API tests"
	@echo "make lint      ruff check + format check"
	@echo "make check     lint + test (run before calling a task done)"
	@echo "make check-ai  ask the configured model to call a tool (use after changing OPSCEND_AI_*)"
	@echo "make eval      score the investigator on failures with known causes (uses the configured model)"
	@echo "make eval-memory  score how incident memory matches repeats and novel errors (no model)"

install:
	cd api && $(UV) sync
	cd web && pnpm install

dev-api:
	cd api && $(UV) run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-web:
	cd web && pnpm dev

worker:
	cd api && $(UV) run arq app.worker.WorkerSettings

migrate:
	cd api && $(UV) run alembic upgrade head

test:
	cd api && $(UV) run pytest

lint:
	cd api && $(UV) run ruff check . && $(UV) run ruff format --check .

format:
	cd api && $(UV) run ruff check . --fix && $(UV) run ruff format .

check: lint test

check-web:
	cd web && pnpm typecheck

check-ai:
	cd api && $(UV) run python -m app.investigator.check

eval:
	cd api && $(UV) run python -m app.evals.runner $(ARGS)

eval-memory:
	cd api && $(UV) run python -m app.evals.memory $(ARGS)
