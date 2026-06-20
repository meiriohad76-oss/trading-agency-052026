from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
from dotenv import dotenv_values, load_dotenv

from agency.paths import REPO_ROOT

DEFAULT_CONFIG_PATH = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
DEFAULT_UNIVERSE_PATH = REPO_ROOT / "research" / "data" / "parquet" / "universe_membership.parquet"
DEFAULT_MANIFEST_ROOT = REPO_ROOT / "research" / "data" / "manifests"
DEFAULT_PARQUET_ROOT = REPO_ROOT / "research" / "data" / "parquet"
SEC_DATASETS = {"sec_company_facts", "sec_form4", "sec_13f"}
CORE_UNIVERSE_COVERAGE_DATASETS = (
    "prices_daily",
    "sec_company_facts",
    "stock_trades",
)
MIN_OPENAI_KEY_LENGTH = 20


def load_live_config_readiness(path: Path | None = None) -> dict[str, object]:
    load_dotenv(override=path is None)
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
        "runtime_signals": list(_strings(payload, "runtime_signals")) if payload else [],
        "runtime_signal_count": len(_strings(payload, "runtime_signals")) if payload else 0,
        "ticker_count": _ticker_count(payload),
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
    coverage_check = _runtime_coverage_check(payload, datasets)
    if coverage_check is not None:
        checks.append(coverage_check)
    if _uses_any(datasets, SEC_DATASETS):
        checks.append(_sec_user_agent_check(payload))
    if _uses(datasets, "news_rss"):
        checks.append(_list_check(payload, "RSS feeds", "rss_feeds"))
    if _uses(datasets, "subscription_emails") or _has_path(payload, "subscription_email_config"):
        checks.append(_subscription_email_check(payload))
    if _uses(datasets, "options_chains"):
        checks.append(_check("Options chains", "WARN", "Forward-chain anomalies are inferred"))
    if _uses(datasets, "stock_trades"):
        checks.append(_massive_credentials_check())
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
    if provider == "massive":
        if _massive_credentials_present():
            return _check("Market data", "PASS", "Massive or Polygon credentials are present")
        return _check("Market data", "BLOCK", "Missing MASSIVE_API_KEY or POLYGON_API_KEY")
    if provider == "yfinance":
        return _check("Market data", "WARN", "yfinance may be stale for current-date bars")
    return _check("Market data", "BLOCK", f"Unknown provider: {provider}")


def _massive_credentials_check() -> dict[str, str]:
    if _massive_credentials_present():
        return _check("Massive market-flow", "PASS", "Massive or Polygon credentials are present")
    return _check("Massive market-flow", "BLOCK", "Missing MASSIVE_API_KEY or POLYGON_API_KEY")


def _subscription_email_check(payload: Mapping[str, object]) -> dict[str, str]:  # noqa: PLR0911
    config_path = _config_path(payload, "subscription_email_config")
    if config_path is None:
        return _check(
            "Subscription emails",
            "WARN",
            "Missing subscription_email_config; paid email agents stay disabled",
        )
    if not config_path.is_file():
        return _check("Subscription emails", "WARN", f"Missing {_display_path(config_path)}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _check("Subscription emails", "WARN", "Config could not be read")
    if not isinstance(config, Mapping):
        return _check("Subscription emails", "WARN", "Config must be a JSON object")
    mode = str(config.get("mode") or "local_eml")
    services = _strings(config, "enabled_services")
    article_llm_enabled = config.get("article_llm_analysis_enabled") is True
    input_path = _config_path(config, "input_path")
    if mode == "local_eml" and (input_path is None or not input_path.exists()):
        return _check(
            "Subscription emails",
            "WARN",
            "Local .eml export folder is not present yet",
        )
    if mode in {"gmail", "outlook", "imap"}:
        username_env = str(config.get("mailbox_username_env") or "SUBSCRIPTION_EMAIL_USERNAME")
        password_env = str(config.get("mailbox_password_env") or "SUBSCRIPTION_EMAIL_PASSWORD")
        missing = [
            name
            for name in (username_env, password_env)
            if os.environ.get(name, "").strip() == ""
        ]
        if not missing:
            return _subscription_email_ready_check(mode, services, article_llm_enabled)
        return _check(
            "Subscription emails",
            "WARN",
            f"Missing mailbox credentials: {', '.join(missing)}",
        )
    return _subscription_email_ready_check(mode, services, article_llm_enabled)


def _subscription_email_ready_check(
    mode: str,
    services: tuple[str, ...],
    article_llm_enabled: bool,
) -> dict[str, str]:
    detail = f"{mode} configured for {len(services)} service(s)"
    if not article_llm_enabled:
        return _check("Subscription emails", "PASS", detail)
    if _openai_key_present():
        return _check("Subscription emails", "PASS", f"{detail}; article LLM ready")
    return _check(
        "Subscription emails",
        "WARN",
        f"{detail}; article LLM enabled but OPENAI_API_KEY is missing",
    )


def _ticker_check(payload: Mapping[str, object]) -> dict[str, str]:
    tickers = _strings(payload, "tickers")
    if tickers and _runtime_universe(payload) != "active":
        return _check("Ticker universe", "PASS", f"{len(tickers)} configured tickers")
    if DEFAULT_UNIVERSE_PATH.is_file():
        count = _active_universe_count(_config_end(payload), DEFAULT_UNIVERSE_PATH)
        if count > 0:
            return _check(
                "Ticker universe",
                "PASS",
                f"{count} active universe tickers from membership parquet",
            )
        return _check("Ticker universe", "BLOCK", "Universe membership parquet has no active rows")
    return _check("Ticker universe", "BLOCK", "No tickers and no universe membership parquet")


def _ticker_count(payload: Mapping[str, object] | None) -> int:
    if payload is None:
        return 0
    tickers = _strings(payload, "tickers")
    if tickers and _runtime_universe(payload) != "active":
        return len(tickers)
    return _active_universe_count(_config_end(payload), DEFAULT_UNIVERSE_PATH)


def _runtime_universe(payload: Mapping[str, object]) -> str:
    value = payload.get("runtime_universe")
    if isinstance(value, str) and value.strip() != "":
        return value.strip().lower()
    return "configured"


def _config_end(payload: Mapping[str, object]) -> date:
    value = payload.get("end")
    if isinstance(value, str) and value.strip() != "":
        return date.fromisoformat(value)
    return date.today()


def _active_universe_count(as_of: date, path: Path) -> int:
    return len(_active_universe_tickers(as_of, path))


def _active_universe_tickers(as_of: date, path: Path) -> set[str]:
    if not path.is_file():
        return set()
    frame = pd.read_parquet(path, columns=["ticker", "start_date", "end_date"])
    if frame.empty:
        return set()
    start = pd.to_datetime(frame["start_date"], errors="coerce").dt.date
    end = pd.to_datetime(frame["end_date"], errors="coerce").dt.date
    active = frame[(start <= as_of) & (end.isna() | (end > as_of))]
    return {str(ticker).upper() for ticker in active["ticker"].dropna().unique()}


def _runtime_coverage_check(
    payload: Mapping[str, object],
    datasets: tuple[str, ...],
) -> dict[str, str] | None:
    if _runtime_universe(payload) != "active":
        return None
    as_of = _config_end(payload)
    active_tickers = _active_universe_tickers(as_of, DEFAULT_UNIVERSE_PATH)
    if not active_tickers:
        return None
    rows = [
        (dataset, _dataset_ticker_count(dataset), len(active_tickers))
        for dataset in CORE_UNIVERSE_COVERAGE_DATASETS
        if _uses(datasets, dataset)
    ]
    gaps = [
        f"{dataset} {count}/{expected}"
        for dataset, count, expected in rows
        if count < expected
    ]
    if gaps:
        return _check(
            "Runtime data coverage",
            "WARN",
            f"Partial active-universe coverage: {', '.join(gaps)}",
        )
    return _check(
        "Runtime data coverage",
        "PASS",
        f"Core datasets cover {len(active_tickers)} active universe tickers",
    )


def _dataset_ticker_count(dataset: str) -> int:
    manifest_path = DEFAULT_MANIFEST_ROOT / f"{dataset}.json"
    if not manifest_path.is_file():
        return 0
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, Mapping):
        return 0
    tickers = payload.get("tickers")
    if isinstance(tickers, list):
        return len({str(ticker).upper() for ticker in tickers if str(ticker).strip()})
    path = payload.get("path")
    if not isinstance(path, str) or path.strip() == "":
        return 0
    return _parquet_ticker_count(DEFAULT_PARQUET_ROOT / path)


def _parquet_ticker_count(path: Path) -> int:
    try:
        if path.is_dir():
            frames = [
                pd.read_parquet(item, columns=["ticker"])
                for item in sorted(path.rglob("*.parquet"))
            ]
            if not frames:
                return 0
            frame = pd.concat(frames, ignore_index=True)
        else:
            frame = pd.read_parquet(path, columns=["ticker"])
    except (OSError, ValueError, KeyError):
        return 0
    if frame.empty:
        return 0
    return int(frame["ticker"].dropna().astype(str).str.upper().nunique())


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


def _config_path(payload: Mapping[str, object], key: str) -> Path | None:
    value = payload.get(key)
    if not isinstance(value, str) or value.strip() == "":
        return None
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _has_path(payload: Mapping[str, object], key: str) -> bool:
    return _config_path(payload, key) is not None


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


def _massive_credentials_present() -> bool:
    return bool(
        os.environ.get("MASSIVE_API_KEY", "").strip()
        or os.environ.get("POLYGON_API_KEY", "").strip()
    )


def _openai_key_present() -> bool:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if _looks_like_openai_key(value):
        return True
    dotenv_value = dotenv_values(REPO_ROOT / ".env").get("OPENAI_API_KEY")
    if isinstance(dotenv_value, str):
        return _looks_like_openai_key(dotenv_value.strip())
    return False


def _looks_like_openai_key(value: str) -> bool:
    return value.startswith("sk-") and len(value) >= MIN_OPENAI_KEY_LENGTH


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
