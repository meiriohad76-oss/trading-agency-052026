from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from news.puller import _normalize, _resolve_rows  # noqa: E402
from news.storage import _with_schema_defaults, write_manifest  # noqa: E402
from news.ticker_resolution import TickerAlias, TickerResolutionRegistry  # noqa: E402


@dataclass(frozen=True)
class NewsRssRepairSummary:
    raw_rows_scanned: int
    newly_resolved_rows: int
    ambiguous_rows: int
    unresolved_rows: int
    output_rows: int
    top_matched_tickers: tuple[dict[str, object], ...]
    dry_run: bool
    output_path: str
    manifest_path: str

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = repair_existing_news_rss(
        input_path=args.input,
        output_path=args.output,
        manifest_path=args.manifest,
        ticker_aliases_path=args.ticker_aliases,
        tickers=tuple(args.ticker),
        min_confidence=args.min_confidence,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary.to_payload(), indent=2, sort_keys=True))
    return 0


def repair_existing_news_rss(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    ticker_aliases_path: Path | None,
    tickers: tuple[str, ...],
    min_confidence: float,
    dry_run: bool,
    clock: Callable[[], datetime] | None = None,
) -> NewsRssRepairSummary:
    fetched_at = (clock or (lambda: datetime.now(UTC)))()
    registry = _ticker_registry(ticker_aliases_path, tickers)
    source = _with_schema_defaults(pd.read_parquet(input_path))
    repaired_rows: list[pd.DataFrame] = []
    preserved_rows: list[dict[str, object]] = []
    newly_resolved_rows = 0

    for raw_row in source.to_dict(orient="records"):
        row = {key: _none_if_missing(value) for key, value in raw_row.items()}
        if _needs_resolution(row):
            resolved = _resolve_rows(
                [row],
                registry=registry,
                keep_unresolved=True,
                min_confidence=min_confidence,
            )
            newly_resolved_rows += sum(
                1
                for item in resolved
                if item.get("ticker_match_status") in {"resolved", "feed_ticker"}
            )
            if resolved:
                repaired_rows.append(_normalize(resolved, fetched_at=fetched_at))
            continue
        preserved_rows.append(row)

    frames: list[pd.DataFrame] = []
    if preserved_rows:
        frames.append(_with_schema_defaults(pd.DataFrame(preserved_rows)))
    frames.extend(repaired_rows)
    output = (
        _with_schema_defaults(pd.concat(frames, ignore_index=True))
        if frames
        else _with_schema_defaults(pd.DataFrame())
    )
    output = (
        output.drop_duplicates(subset=["source_id"], keep="last")
        .sort_values(["timestamp_as_of", "ticker", "source_id"], na_position="last")
        .reset_index(drop=True)
    )

    summary = _summary(
        output,
        raw_rows_scanned=len(source),
        newly_resolved_rows=newly_resolved_rows,
        dry_run=dry_run,
        output_path=output_path,
        manifest_path=manifest_path,
    )
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.to_parquet(output_path, engine="pyarrow", compression="snappy", index=False)
        write_manifest(
            manifest_path,
            output_path,
            fetched_at=fetched_at,
            resolution_min_confidence=min_confidence,
        )
    return summary


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve already-collected generic RSS rows into ticker-linked news rows.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ticker-aliases", type=Path)
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--min-confidence", type=float, default=0.70)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _ticker_registry(
    aliases_path: Path | None,
    tickers: tuple[str, ...],
) -> TickerResolutionRegistry:
    aliases: list[TickerAlias] = []
    ambiguous_symbols: list[str] | None = None
    if aliases_path is not None:
        payload = json.loads(aliases_path.read_text(encoding="utf-8"))
        aliases = [_alias_from_payload(item) for item in payload.get("aliases", [])]
        if "ambiguous_symbols" in payload:
            ambiguous_symbols = [str(item) for item in payload["ambiguous_symbols"]]
    active_tickers = {ticker.upper() for ticker in tickers}
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


def _needs_resolution(row: dict[str, object]) -> bool:
    ticker = _clean_text(row.get("ticker"))
    if ticker:
        return False
    status = _clean_text(row.get("ticker_match_status"))
    return status in {None, "", "unresolved", "ambiguous"}


def _summary(
    frame: pd.DataFrame,
    *,
    raw_rows_scanned: int,
    newly_resolved_rows: int,
    dry_run: bool,
    output_path: Path,
    manifest_path: Path,
) -> NewsRssRepairSummary:
    status = frame["ticker_match_status"].fillna("")
    tickers = [
        ticker.upper()
        for ticker in frame["ticker"].dropna().astype(str)
        if ticker.strip()
    ]
    top_matched_tickers = tuple(
        {"ticker": ticker, "rows": rows}
        for ticker, rows in Counter(tickers).most_common(10)
    )
    return NewsRssRepairSummary(
        raw_rows_scanned=raw_rows_scanned,
        newly_resolved_rows=newly_resolved_rows,
        ambiguous_rows=int((status == "ambiguous").sum()),
        unresolved_rows=int((status == "unresolved").sum()),
        output_rows=len(frame),
        top_matched_tickers=top_matched_tickers,
        dry_run=dry_run,
        output_path=str(output_path),
        manifest_path=str(manifest_path),
    )


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _none_if_missing(value: object) -> object:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


if __name__ == "__main__":
    raise SystemExit(main())
