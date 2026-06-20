#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from fundamentals.fmp_client import (  # noqa: E402
    FmpClient,
    FmpProviderError,
    build_fmp_state,
    not_configured_state,
    provider_error_state,
)

DEFAULT_OUTPUT_DIR = ROOT / "research" / "data" / "state" / "fundamentals" / "fmp"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull FMP earnings and analyst estimate state.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tickers", nargs="+", help="Ticker symbols to pull.")
    group.add_argument("--universe-file", type=Path, help="Text file with one ticker per line.")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    result = pull_tickers(_tickers(args), output_dir=args.output_dir, delay=args.delay)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["errors"] == result["tickers"] and result["tickers"] else 0


def pull_tickers(tickers: list[str], *, output_dir: Path, delay: float = 0.5) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("FMP_API_KEY", "").strip()
    summary = {"ok": 0, "errors": 0, "not_configured": 0, "tickers": len(tickers)}
    if not api_key:
        for ticker in tickers:
            _atomic_write_json(output_dir / f"{ticker}.json", not_configured_state(ticker))
            print(f"NOT_CONFIGURED {ticker}")
            summary["not_configured"] += 1
        return summary

    client = FmpClient(api_key=api_key)
    for ticker in tickers:
        try:
            state = build_fmp_state(ticker, client)
            _atomic_write_json(output_dir / f"{ticker}.json", state)
            print(f"OK {ticker}")
            summary["ok"] += 1
        except FmpProviderError as exc:
            _atomic_write_json(output_dir / f"{ticker}.json", provider_error_state(ticker, str(exc)))
            print(f"ERR {ticker}: {exc}", file=sys.stderr)
            summary["errors"] += 1
        time.sleep(max(delay, 0.0))
    return summary


def _tickers(args: argparse.Namespace) -> list[str]:
    raw = args.tickers or args.universe_file.read_text(encoding="utf-8").splitlines()
    return sorted({str(ticker).upper().strip() for ticker in raw if str(ticker).strip()})


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
