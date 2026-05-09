from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from data_refresh.types import DATASETS


@dataclass(frozen=True)
class RefreshConfigOverrides:
    start: date | None = None
    end: date | None = None
    datasets: tuple[str, ...] = ()
    tickers: tuple[str, ...] = ()
    rss_feeds: tuple[str, ...] = ()
    filer_ciks: tuple[str, ...] = ()
    cusip_map: Path | None = None
    activity_alerts_csv: Path | None = None
    sec_user_agent: str | None = None
    workers: int | None = None
    include_etfs: bool | None = None
    refresh: bool | None = None
    dry_run: bool | None = None
    market_data_provider: str | None = None
    market_data_feed: str | None = None
    market_data_adjustment: str | None = None
    market_data_base_url: str | None = None
    massive_base_url: str | None = None
    runtime_signals: tuple[str, ...] = ()


def load_refresh_config(path: Path, *, repo_root: Path) -> RefreshConfigOverrides:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("refresh config must be a JSON object")
    return RefreshConfigOverrides(
        start=_optional_date(payload, "start"),
        end=_optional_date(payload, "end"),
        datasets=_datasets(payload),
        tickers=_string_tuple(payload, "tickers"),
        rss_feeds=_string_tuple(payload, "rss_feeds"),
        filer_ciks=_string_tuple(payload, "filer_ciks"),
        cusip_map=_optional_path(payload, "cusip_map", repo_root=repo_root),
        activity_alerts_csv=_optional_path(payload, "activity_alerts_csv", repo_root=repo_root),
        sec_user_agent=_optional_string(payload, "sec_user_agent"),
        workers=_optional_int(payload, "workers"),
        include_etfs=_optional_bool(payload, "include_etfs"),
        refresh=_optional_bool(payload, "refresh"),
        dry_run=_optional_bool(payload, "dry_run"),
        market_data_provider=_optional_string(payload, "market_data_provider"),
        market_data_feed=_optional_string(payload, "market_data_feed"),
        market_data_adjustment=_optional_string(payload, "market_data_adjustment"),
        market_data_base_url=_optional_string(payload, "market_data_base_url"),
        massive_base_url=_optional_string(payload, "massive_base_url"),
        runtime_signals=_string_tuple(payload, "runtime_signals"),
    )


def _datasets(payload: Mapping[str, Any]) -> tuple[str, ...]:
    datasets = _string_tuple(payload, "datasets")
    unknown = sorted(set(datasets).difference(DATASETS))
    if unknown:
        raise ValueError(f"unknown dataset(s): {unknown}")
    return datasets


def _string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key not in payload or payload[key] is None:
        return ()
    value = payload[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{key} must be a list of strings")
    return tuple(value)


def _optional_date(payload: Mapping[str, Any], key: str) -> date | None:
    value = _optional_string(payload, key)
    return None if value is None else date.fromisoformat(value)


def _optional_path(payload: Mapping[str, Any], key: str, *, repo_root: Path) -> Path | None:
    value = _optional_string(payload, key)
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return int(value)


def _optional_bool(payload: Mapping[str, Any], key: str) -> bool | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value
