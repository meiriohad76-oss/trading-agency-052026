from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.extraction_plan import build_extraction_plan  # noqa: E402
from data_refresh.signal_lane_policy import lanes_by_cadence, policies_for_lanes  # noqa: E402
from data_refresh.types import RefreshBatchConfig  # noqa: E402

from research.scripts.run_data_refresh_batch import _batch_config, _load_overrides  # noqa: E402

DEFAULT_OUTPUT_ROOT = ROOT / "research" / "results" / "latest-incremental-refresh-plan"


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    overrides = _load_overrides(args.config)
    config = _batch_config(args, overrides)
    payload = build_incremental_refresh_payload(config, lanes=_runtime_lanes(args.config))
    _write_payload(payload, args.output_root)
    print(
        json.dumps(
            {
                "output_root": _display_path(args.output_root),
                "datasets": len(payload["datasets"]),
            },
            sort_keys=True,
        )
    )
    return 0


def build_incremental_refresh_payload(
    config: RefreshBatchConfig,
    *,
    lanes: tuple[str, ...],
) -> dict[str, object]:
    generated_at = datetime.now(UTC)
    decisions = build_extraction_plan(config, now=generated_at)
    policies = policies_for_lanes(lanes)
    return {
        "schema_version": "0.1.0",
        "generated_at": generated_at.isoformat(),
        "config": {
            "datasets": list(config.datasets),
            "tickers": list(config.tickers),
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "extraction_mode": config.extraction_mode,
        },
        "datasets": [decision.as_dict() for decision in decisions],
        "signal_lane_cadence": lanes_by_cadence(lanes),
        "signal_lanes": [
            {
                "lane": policy.lane,
                "dataset": policy.dataset,
                "cadence": policy.cadence,
                "update_window": policy.update_window,
                "extraction_rule": policy.extraction_rule,
                "operational_note": policy.operational_note,
            }
            for policy in policies
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan baseline vs incremental data extraction before running refresh jobs."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "live-refresh.local.json",
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
    (output_root / "incremental-refresh-plan.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "incremental-refresh-plan.md").write_text(
        _markdown(payload),
        encoding="utf-8",
    )


def _markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Incremental Data Extraction Plan",
        "",
        f"Generated at: `{payload['generated_at']}`",
        "",
        "## Dataset Decisions",
        "",
        "| Dataset | Action | Tickers | Window | Reason |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in payload["datasets"]:
        if not isinstance(item, dict):
            continue
        window = _window_text(item)
        lines.append(
            "| "
            f"{item['dataset']} | {item['action']} | {item['ticker_count']} | "
            f"{window} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Signal Lane Cadence",
            "",
            "| Lane | Dataset | Cadence | Update window | Extraction rule |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload["signal_lanes"]:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| "
            f"{item['lane']} | {item['dataset']} | {item['cadence']} | "
            f"{item['update_window']} | {item['extraction_rule']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _window_text(item: dict[str, object]) -> str:
    start = item.get("start")
    end = item.get("end")
    if not start and not end:
        return "n/a"
    return f"{start or '...'} to {end or '...'}"


def _runtime_lanes(config_path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    value = payload.get("runtime_signals") if isinstance(payload, dict) else None
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
