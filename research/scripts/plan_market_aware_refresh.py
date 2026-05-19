from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.market_batching import build_market_aware_batch_plan  # noqa: E402

from research.scripts.run_data_refresh_batch import _batch_config, _load_overrides  # noqa: E402

DEFAULT_OUTPUT_ROOT = ROOT / "research" / "results" / "latest-market-aware-refresh-plan"


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    overrides = _load_overrides(args.config)
    config = _batch_config(args, overrides)
    now = _parse_datetime(args.now) if args.now else datetime.now(UTC)
    payload = build_market_aware_batch_plan(
        config,
        lanes=_runtime_lanes(args.config),
        now=now,
    )
    _write_payload(payload, args.output_root)
    summary = payload["summary"]
    if not isinstance(summary, dict):
        raise TypeError("summary must be a mapping")
    session = _mapping(payload["market_session"])
    print(
        json.dumps(
            {
                "output_root": _display_path(args.output_root),
                "phase": session["phase"],
                "run_now_datasets": summary["run_now_dataset_count"],
                "deferred_datasets": summary["deferred_dataset_count"],
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan market-session-aware data refresh batches."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "live-refresh.local.json",
    )
    parser.add_argument(
        "--now",
        help="ISO datetime. Naive values are interpreted as New York time.",
    )
    parser.add_argument("--start", type=_date)
    parser.add_argument("--end", type=_date)
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--rss-feed", action="append")
    parser.add_argument("--filer-cik", action="append")
    parser.add_argument("--cusip-map", type=Path)
    parser.add_argument("--activity-alerts-csv", type=Path)
    parser.add_argument("--subscription-email-config", type=Path)
    parser.add_argument("--sec-user-agent")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--include-etfs", action=argparse.BooleanOptionalAction)
    parser.add_argument("--refresh", action=argparse.BooleanOptionalAction)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction)
    parser.add_argument("--market-data-provider", choices=("yfinance", "alpaca", "massive"))
    parser.add_argument("--market-data-feed")
    parser.add_argument("--market-data-adjustment")
    parser.add_argument("--market-data-base-url")
    parser.add_argument("--massive-base-url")
    parser.add_argument("--stock-trades-start", type=_date)
    parser.add_argument("--stock-trades-end", type=_date)
    parser.add_argument("--stock-trades-limit", type=int)
    parser.add_argument("--stock-trades-max-pages-per-day", type=int)
    parser.add_argument("--stock-trades-order", choices=("asc", "desc"))
    parser.add_argument("--extraction-mode", choices=("auto", "baseline", "incremental", "force"))
    parser.add_argument("--sec-company-facts-max-age-days", type=int)
    parser.add_argument("--sec-form4-max-age-days", type=int)
    parser.add_argument("--sec-13f-max-age-days", type=int)
    parser.add_argument("--news-rss-max-age-minutes", type=int)
    parser.add_argument("--subscription-email-max-age-minutes", type=int)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def _write_payload(payload: dict[str, object], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "market-aware-refresh-plan.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "market-aware-refresh-plan.md").write_text(
        _markdown(payload),
        encoding="utf-8",
    )


def _markdown(payload: dict[str, object]) -> str:
    session = payload["market_session"]
    if not isinstance(session, dict):
        raise TypeError("market_session must be a mapping")
    lines = [
        "# Market-Aware Data Refresh Plan",
        "",
        f"Generated at: `{payload['generated_at']}`",
        f"Market phase: `{session['phase']}`",
        f"Trading day: `{session['is_trading_day']}`",
        f"Regular close: `{session['regular_close_at'] or 'n/a'}`",
        "",
        "## Dataset Batches",
        "",
        "| Dataset | Batch action | Priority | Cadence | Batch size | Extraction | Reason |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for item in _dict_rows(payload, "datasets"):
        lines.append(
            "| "
            f"{item['dataset']} | {item['batch_action']} | {item['priority']} | "
            f"{_empty(item['cadence_minutes'])} | {_empty(item['max_tickers_per_batch'])} | "
            f"{item['extraction_action']} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Signal Lane Batches",
            "",
            "| Lane | Dataset | Batch action | Priority | Cadence | Reason |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for item in _dict_rows(payload, "signal_lanes"):
        lines.append(
            "| "
            f"{item['lane']} | {item['dataset']} | {item['batch_action']} | "
            f"{item['priority']} | {_empty(item['cadence_minutes'])} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Massive Raw Data Orchestrator",
            "",
            "| Raw lane | Purpose | Source dataset | Mode | Action | Priority | Cadence | Tier | Window | Budget | Reason |",
            "| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for item in _dict_rows(payload, "massive_lanes"):
        lines.append(
            "| "
            f"{item['label']} | {item['purpose']} | {item['raw_source_dataset']} | "
            f"{item['acquisition_mode']} | {item['batch_action']} | {item['priority']} | "
            f"{_empty(item['cadence_minutes'])} | {item['ticker_tier']} | "
            f"{item['window_label']} | {item['request_budget_label']} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Derived Signal Requirements",
            "",
            "| Signal lane | Requires raw lanes | Status | Reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    massive = payload.get("massive_orchestrator")
    derived_payload = massive if isinstance(massive, dict) else payload
    for item in _dict_rows(derived_payload, "derived_signal_lanes"):
        requirements = item.get("requires_raw_lanes")
        lines.append(
            "| "
            f"{item['signal_lane']} | {_joined(requirements)} | "
            f"{item['status_hint']} | {item['reason']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _dict_rows(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _empty(value: object) -> str:
    return "n/a" if value is None else str(value)


def _joined(value: object) -> str:
    if not isinstance(value, list):
        return "n/a"
    return ", ".join(str(item) for item in value) or "n/a"


def _display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed
    return parsed.astimezone(UTC)


def _runtime_lanes(config_path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    value = payload.get("runtime_signals")
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected a mapping")
    return cast(Mapping[str, object], value)


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
