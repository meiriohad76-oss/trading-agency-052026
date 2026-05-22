from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SHORT_FEED_PARTS = 2
TICKER_FEED_PARTS = 3

sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from news.puller import pull_rss_feeds  # noqa: E402
from news.rss import FeedSpec  # noqa: E402
from news.ticker_resolution import TickerAlias, TickerResolutionRegistry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull forward RSS/news headlines.")
    parser.add_argument(
        "--feed",
        action="append",
        required=True,
        help="Feed spec as SOURCE_NAME,URL or SOURCE_NAME,TICKER,URL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "news_rss.parquet",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "news_rss.json",
    )
    parser.add_argument(
        "--ticker",
        action="append",
        default=[],
        help="Active ticker to use for generic RSS ticker resolution. Repeatable.",
    )
    parser.add_argument(
        "--ticker-aliases",
        type=Path,
        help="JSON alias registry for generic RSS ticker resolution.",
    )
    parser.add_argument(
        "--universe-path",
        type=Path,
        help="Parquet/CSV/JSON universe file with a ticker column.",
    )
    parser.add_argument(
        "--resolve-generic-tickers",
        action="store_true",
        help="Resolve generic RSS headlines into ticker-specific rows.",
    )
    parser.add_argument(
        "--news-resolution-min-confidence",
        type=float,
        default=0.70,
        help="Minimum ticker-match confidence for resolved RSS rows.",
    )
    parser.add_argument(
        "--keep-unresolved-generic-news",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep unresolved generic RSS rows for audit and coverage.",
    )
    parser.add_argument(
        "--sec-user-agent",
        default=None,
        help="SEC-compliant User-Agent for SEC RSS feeds; defaults to SEC_USER_AGENT.",
    )
    args = parser.parse_args()
    feeds = [_feed_spec(value) for value in args.feed]
    registry = _ticker_registry(args.ticker_aliases, args.ticker, args.universe_path)
    summary = asyncio.run(
        pull_rss_feeds(
            feeds=feeds,
            parquet_path=args.output,
            manifest_path=args.manifest,
            ticker_registry=registry,
            resolve_generic_tickers=args.resolve_generic_tickers,
            keep_unresolved=args.keep_unresolved_generic_news,
            min_confidence=args.news_resolution_min_confidence,
            user_agent=args.sec_user_agent or os.environ.get("SEC_USER_AGENT"),
        )
    )
    print(summary)


def _feed_spec(value: str) -> FeedSpec:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) == SHORT_FEED_PARTS:
        return FeedSpec(source_name=parts[0], url=parts[1])
    if len(parts) == TICKER_FEED_PARTS:
        return FeedSpec(source_name=parts[0], ticker=parts[1], url=parts[2])
    raise ValueError("--feed must be SOURCE_NAME,URL or SOURCE_NAME,TICKER,URL")


def _ticker_registry(
    aliases_path: Path | None,
    tickers: list[str],
    universe_path: Path | None,
) -> TickerResolutionRegistry:
    aliases: list[TickerAlias] = []
    ambiguous_symbols: list[str] | None = None
    if aliases_path is not None:
        payload = json.loads(aliases_path.read_text(encoding="utf-8"))
        aliases = [_alias_from_payload(item) for item in payload.get("aliases", [])]
        if "ambiguous_symbols" in payload:
            ambiguous_symbols = [str(item) for item in payload["ambiguous_symbols"]]
    active_tickers = {ticker.upper() for ticker in tickers}
    if universe_path is not None:
        active_tickers.update(_read_universe_tickers(universe_path))
    if not active_tickers:
        active_tickers.update(alias.ticker for alias in aliases)
    return TickerResolutionRegistry(
        aliases=aliases,
        active_tickers=active_tickers,
        ambiguous_symbols=ambiguous_symbols,
    )


def _alias_from_payload(payload: dict[str, object]) -> TickerAlias:
    return TickerAlias(
        ticker=str(payload["ticker"]),
        cik=None if payload.get("cik") is None else str(payload["cik"]),
        legal_names=_string_tuple(payload.get("legal_names")),
        brand_aliases=_string_tuple(payload.get("brand_aliases")),
        allow_plain_brand=bool(payload.get("allow_plain_brand", False)),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def _read_universe_tickers(path: Path) -> set[str]:
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() == ".json":
        frame = pd.read_json(path)
    else:
        raise ValueError("--universe-path must be a parquet, csv, or json file")
    if "ticker" not in frame.columns:
        raise ValueError("--universe-path must contain a ticker column")
    if "end_date" in frame.columns:
        end_dates = pd.to_datetime(frame["end_date"], errors="coerce")
        frame = frame[end_dates.isna()]
    return {str(ticker).upper() for ticker in frame["ticker"].dropna() if str(ticker).strip()}


if __name__ == "__main__":
    main()
