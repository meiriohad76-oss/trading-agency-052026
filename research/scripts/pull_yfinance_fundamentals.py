#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from fundamentals.yfinance_snapshot import FetchError, pull_yfinance_snapshot  # noqa: E402

DEFAULT_OUTPUT_DIR = ROOT / "research" / "data" / "state" / "fundamentals" / "yfinance"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull yfinance fundamentals snapshots.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tickers", nargs="+", help="Ticker symbols to pull.")
    group.add_argument("--universe-file", type=Path, help="Text file with one ticker per line.")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    tickers = _tickers(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    errors = 0
    for ticker in tickers:
        try:
            snapshot = pull_yfinance_snapshot(ticker)
            _atomic_write_json(args.output_dir / f"{ticker}.json", snapshot.to_dict())
            print(f"OK {ticker}")
            ok += 1
        except FetchError as exc:
            print(f"ERR {ticker}: {exc}", file=sys.stderr)
            errors += 1
        time.sleep(max(args.delay, 0.0))
    print(json.dumps({"ok": ok, "errors": errors, "tickers": len(tickers)}, sort_keys=True))
    return 1 if errors == len(tickers) and tickers else 0


def _tickers(args: argparse.Namespace) -> list[str]:
    raw = args.tickers or args.universe_file.read_text(encoding="utf-8").splitlines()
    return sorted({str(ticker).upper().strip() for ticker in raw if str(ticker).strip()})


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
