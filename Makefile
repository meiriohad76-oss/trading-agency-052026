VENV ?= .venv

ifeq ($(OS),Windows_NT)
PYTHON ?= py -3.14
VENV_BIN := $(VENV)/Scripts
else
PYTHON ?= python3.14
VENV_BIN := $(VENV)/bin
endif

VENV_PYTHON := $(VENV_BIN)/python

.PHONY: setup lint type-check test pit-guard db-up db-down migrate seed-demo dev-up serve smoke-local backup-db restore-db compose-config

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e ".[dev]"
	$(VENV_BIN)/pre-commit install
	$(MAKE) lint
	$(MAKE) type-check
	$(MAKE) test

lint:
	$(VENV_PYTHON) -m ruff check .
	$(VENV_PYTHON) scripts/check_pit_bypass.py

type-check:
	$(VENV_PYTHON) -m mypy src research

test:
	$(VENV_PYTHON) -m pytest

pit-guard:
	$(VENV_PYTHON) scripts/check_pit_bypass.py

db-up:
	docker compose -f docker/docker-compose.yml up -d postgres

db-down:
	docker compose -f docker/docker-compose.yml down -v

migrate:
	$(VENV_PYTHON) -m alembic upgrade head

seed-demo:
	$(VENV_PYTHON) scripts/seed_demo_runtime.py

dev-up: db-up migrate seed-demo

serve:
	$(VENV_PYTHON) -m uvicorn agency.app:app --host 127.0.0.1 --port 8000

smoke-local:
	$(VENV_PYTHON) scripts/check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1

backup-db:
	$(VENV_PYTHON) scripts/backup_postgres.py $(BACKUP)

restore-db:
	$(VENV_PYTHON) scripts/restore_postgres.py $(BACKUP)

compose-config:
	docker compose -f docker/docker-compose.yml config
