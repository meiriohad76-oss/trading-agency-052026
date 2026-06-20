from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from agency.paths import REPO_ROOT

DEFAULT_TICKER_REFERENCE_PATH = REPO_ROOT / "research" / "data" / "reference" / "massive_ticker_details.json"


def load_ticker_reference_index(
    path: Path = DEFAULT_TICKER_REFERENCE_PATH,
) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    return _reference_index(payload)


def _reference_index(payload: Mapping[str, object]) -> dict[str, dict[str, object]]:
    rows = payload.get("rows")
    if isinstance(rows, list | tuple):
        return _rows_index(rows)
    tickers = payload.get("tickers")
    if isinstance(tickers, Mapping):
        return {
            ticker.upper(): dict(row)
            for ticker, row in tickers.items()
            if isinstance(ticker, str) and isinstance(row, Mapping)
        }
    return {}


def _rows_index(rows: list[object] | tuple[object, ...]) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ticker = _text(row.get("ticker")).upper()
        if not ticker:
            continue
        index[ticker] = dict(cast(Mapping[str, Any], row))
    return index


def _text(value: object) -> str:
    return str(value or "").strip()
