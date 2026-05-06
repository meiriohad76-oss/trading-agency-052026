# Trading Agency v2

[![CI](https://github.com/meiriohad76-oss/trading-agency-052026/actions/workflows/ci.yml/badge.svg)](https://github.com/meiriohad76-oss/trading-agency-052026/actions/workflows/ci.yml)

Trading Agency v2 is a supervised, Python-first equity research and paper-trading assistant. The project starts with a point-in-time research pipeline, versioned schemas, and strict testing discipline before any production trading workflow is built.

## Project Docs

- [v2 plan](docs/v2-plan.md)
- [research brief](docs/research-brief.md)
- [working model](docs/working-model.md)

## First-Time Setup

This repo uses Python 3.14 and standard `pip` tooling.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\pre-commit install
.\.venv\Scripts\ruff check .
.\.venv\Scripts\mypy src research
.\.venv\Scripts\pytest
```

On systems with `make`, the equivalent one-command setup is:

```sh
make setup
```
