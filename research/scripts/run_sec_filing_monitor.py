#!/usr/bin/env python3
# research/scripts/run_sec_filing_monitor.py
"""Run the SEC filing monitor: detect new filings, analyze, store results.

Usage:
    python run_sec_filing_monitor.py --tickers AAPL MSFT NVDA
    python run_sec_filing_monitor.py --dry-run
    python run_sec_filing_monitor.py  # uses checkpoint; processes universe
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "research" / "src"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from sec.cik import cik_lookup_for_tickers, parse_company_tickers
from sec.client import SecClient, SecClientConfig
from sec.filing_extractor import FilingExtractor
from sec.filing_monitor import FilingCheckpoint, FilingMonitor

ANALYSES_DIR = REPO_ROOT / "research" / "data" / "state" / "sec_filings" / "analyses"
CHECKPOINT_PATH = REPO_ROOT / "research" / "data" / "state" / "sec_filings" / "checkpoint.json"
DEFAULT_LOOKBACK_DAYS = 7


async def main(args: argparse.Namespace) -> int:
    # ── Load CIK map from EDGAR company_tickers.json ─────────────────────────
    config = SecClientConfig(
        user_agent=os.environ.get("SEC_USER_AGENT", "trading-agency dev@example.com")
    )
    async with SecClient(config) as client:
        raw_tickers = await client.company_tickers()
        cik_mapping = parse_company_tickers(raw_tickers)

    tickers = args.tickers or _load_universe()
    matched, missing = cik_lookup_for_tickers(tickers, cik_mapping)

    if missing:
        for t in missing:
            print(f"  WARN: no CIK for {t}")

    cik_map = {ticker: info.cik for ticker, info in matched.items()}

    # ── Determine since date ─────────────────────────────────────────────────
    checkpoint = FilingCheckpoint(path=CHECKPOINT_PATH)
    since = checkpoint.load() or (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    print(f"Checking for new filings since {since} for {len(cik_map)} ticker(s)...")

    # ── Detect new filings ───────────────────────────────────────────────────
    async with SecClient(config) as client:
        monitor = FilingMonitor(client=client, cik_map=cik_map)
        new_filings = await monitor.check_new_filings(list(cik_map.keys()), since=since)

    if not new_filings:
        print(f"No new filings since {since}.")
        if not args.dry_run:
            checkpoint.save(date.today())
        return 0

    print(f"Found {len(new_filings)} new filing(s):")
    for f in new_filings:
        print(f"  {f.ticker} {f.form} filed {f.filing_date} → {f.accession_number}")

    if args.dry_run:
        print("(dry run — not fetching or analyzing)")
        return 0

    # ── Fetch, extract, and analyze each filing ──────────────────────────────
    from fundamentals.filing_analyst import FilingAnalyst
    extractor = FilingExtractor()
    analyst = FilingAnalyst()

    async with SecClient(config) as client:
        for filing in new_filings:
            try:
                html = await client.get_text(filing.document_url)
                extract = extractor.extract(filing.form, html)
                analysis = analyst.analyze(filing, extract)

                out_dir = ANALYSES_DIR / filing.ticker
                out_dir.mkdir(parents=True, exist_ok=True)
                accession_safe = filing.accession_number.replace("/", "-")
                out_path = out_dir / f"{accession_safe}.json"
                out_path.write_text(
                    json.dumps(analysis.to_dict(), indent=2, default=str),
                    encoding="utf-8",
                )
                sentiment_label = "✓" if analysis.sentiment == "BULLISH" else (
                    "✗" if analysis.sentiment == "BEARISH" else "="
                )
                print(
                    f"  {sentiment_label} {filing.ticker} {filing.form} "
                    f"[{analysis.sentiment}] — {analysis.headline_sentence[:80]}"
                )

            except Exception as exc:
                print(f"  ERR {filing.ticker} {filing.form}: {exc}", file=sys.stderr)

    checkpoint.save(date.today())
    print(f"\nCheckpoint updated to {date.today()}.")
    return 0


def _load_universe() -> list[str]:
    universe_path = REPO_ROOT / "research" / "data" / "universe.txt"
    if universe_path.is_file():
        return [
            line.strip().upper()
            for line in universe_path.read_text().splitlines()
            if line.strip()
        ]
    return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SEC filing monitor.")
    parser.add_argument("--tickers", nargs="*", help="Override tickers (default: universe).")
    parser.add_argument("--dry-run", action="store_true", help="Detect only; don't fetch or analyze.")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
