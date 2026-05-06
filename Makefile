VENV ?= .venv

ifeq ($(OS),Windows_NT)
PYTHON ?= py -3.14
VENV_BIN := $(VENV)/Scripts
else
PYTHON ?= python3.14
VENV_BIN := $(VENV)/bin
endif

VENV_PYTHON := $(VENV_BIN)/python

.PHONY: setup lint type-check test

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

type-check:
	$(VENV_PYTHON) -m mypy src research

test:
	$(VENV_PYTHON) -m pytest
