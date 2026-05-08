from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
DEFAULT_UNIVERSE_PATH = REPO_ROOT / "research" / "data" / "parquet" / "universe_membership.parquet"
SEC_DATASETS = {"sec_company_facts", "sec_form4", "sec_13f"}


def load_live_config_readiness(path: Path | None = None) -> dict[str, object]:
    load_dotenv()
    config_path = path or live_refresh_config_path()
    payload = _read_config(config_path)
    checks = _checks(config_path, payload)
    blocker_count = sum(1 for check in checks if check["status"] == "BLOCK")
    warning_count = sum(1 for check in checks if check["status"] == "WARN")
    state = _state(blocker_count, warning_count)
    return {
        "ready": blocker_count == 0,
        "state": state,
        "status_label": _status_label(state),
        "status_class": _status_class(state),
        "config_path": _display_path(config_path),
        "provider": _market_provider(payload),
        "dataset_count": len(_datasets(payload)),
        "ticker_count": len(_strings(payload, "tickers")) if payload is not None else 0,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "checks": checks,
    }


def live_refresh_config_path() -> Path:
    value = os.environ.get("LIVE_REFRESH_CONFIG_PATH")
    if value is None or value.strip() == "":
        return DEFAULT_CONFIG_PATH
    return Path(value)


def _checks(config_path: Path, payload: Mapping[str, object] | None) -> list[dict[str, str]]:
    if payload is None:
        return [_check("Config file", "BLOCK", f"Missing {_display_path(config_path)}")]
    datasets = _datasets(payload)
    checks = [
        _check("Config file", "PASS", f"Loaded {_display_path(config_path)}"),
        _ticker_check(payload),
        _market_data_check(payload),
    ]
    if _uses_any(datasets, SEC_DATASETS):
        checks.append(_sec_user_agent_check(payload))
    if _uses(datasets, "news_rss"):
        checks.append(_list_check(payload, "RSS feeds", "rss_feeds"))
    if _uses(datasets, "sec_13f"):
        checks.extend([
            _list_check(payload, "13F filers", "filer_ciks"),
            _file_check(payload, "CUSIP map", "cusip_map"),
        ])
    if _uses(datasets, "unusual_activity_alerts"):
        checks.append(_file_check(payload, "Activity alerts CSV", "activity_alerts_csv"))
    return checks


def _market_data_check(payload: Mapping[str, object]) -> dict[str, str]:
    provider = _market_provider(payload)
    if provider == "alpaca":
        missing = [
            name
            for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")
            if os.environ.get(name, "").strip() == ""
        ]
        if missing:
            return _check("Market data", "BLOCK", f"Missing {', '.join(missing)}")
        return _check("Market data", "PASS", "Alpaca credentials are present")
    if provider == "yfinance":
        return _check("Market data", "WARN", "yfinance may be stale for current-date bars")
    return _check("Market data", "BLOCK", f"Unknown provider: {provider}")


def _ticker_check(payload: Mapping[str, object]) -> dict[str, str]:
    tickers = _strings(payload, "tickers")
    if tickers:
        return _check("Ticker universe", "PASS", f"{len(tickers)} configured tickers")
    if DEFAULT_UNIVERSE_PATH.is_file():
        return _check("Ticker universe", "PASS", "Universe membership parquet is present")
    return _check("Ticker universe", "BLOCK", "No tickers and no universe membership parquet")


def _sec_user_agent_check(payload: Mapping[str, object]) -> dict[str, str]:
    value = payload.get("sec_user_agent")
    if isinstance(value, str) and value.strip() != "":
        return _check("SEC User-Agent", "PASS", "sec_user_agent is configured")
    if os.environ.get("SEC_USER_AGENT", "").strip() != "":
        return _check("SEC User-Agent", "PASS", "SEC_USER_AGENT is present")
    return _check("SEC User-Agent", "BLOCK", "Missing SEC_USER_AGENT")


def _list_check(payload: Mapping[str, object], label: str, key: str) -> dict[str, str]:
    values = _strings(payload, key)
    if values:
        return _check(label, "PASS", f"{len(values)} configured")
    return _check(label, "BLOCK", f"Missing {key}")


def _file_check(payload: Mapping[str, object], label: str, key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, str) or value.strip() == "":
        return _check(label, "BLOCK", f"Missing {key}")
    path = Path(value)
    path = path if path.is_absolute() else REPO_ROOT / path
    if path.is_file():
        return _check(label, "PASS", f"{_display_path(path)} exists")
    return _check(label, "BLOCK", f"Missing {_display_path(path)}")


def _check(label: str, status: str, detail: str) -> dict[str, str]:
    return {
        "label": label,
        "status": status,
        "status_class": _status_class(status.lower()),
        "detail": detail,
    }


def _read_config(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return cast(Mapping[str, object], payload) if isinstance(payload, Mapping) else None


def _datasets(payload: Mapping[str, object] | None) -> tuple[str, ...]:
    if payload is None:
        return ()
    values = _strings(payload, "datasets")
    return values or ("prices_daily", *tuple(sorted(SEC_DATASETS)), "news_rss")


def _strings(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip() != "")


def _market_provider(payload: Mapping[str, object] | None) -> str:
    value = payload.get("market_data_provider") if payload is not None else None
    if isinstance(value, str) and value.strip() != "":
        return value.strip().lower()
    env_provider = os.environ.get("MARKET_DATA_PROVIDER", "").strip().lower()
    return env_provider or "yfinance"


def _uses(datasets: tuple[str, ...], dataset: str) -> bool:
    return not datasets or dataset in datasets


def _uses_any(datasets: tuple[str, ...], candidates: set[str]) -> bool:
    return not datasets or bool(candidates.intersection(datasets))


def _state(blocker_count: int, warning_count: int) -> str:
    if blocker_count > 0:
        return "blocked"
    if warning_count > 0:
        return "warning"
    return "ready"


def _status_label(state: str) -> str:
    return {"ready": "Ready", "warning": "Needs Attention", "blocked": "Blocked"}.get(state, state)


def _status_class(state: str) -> str:
    if state in {"ready", "pass"}:
        return "pass"
    if state in {"warning", "warn"}:
        return "warn"
    return "block"


def _display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
