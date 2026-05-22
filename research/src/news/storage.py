from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

NEWS_COLUMNS = [
    "ticker",
    "feed_url",
    "feed_name",
    "title",
    "url",
    "summary",
    "published_at",
    "source",
    "source_tier",
    "source_id",
    "source_url",
    "timestamp_observed",
    "timestamp_as_of",
    "freshness",
    "confidence",
    "verification_level",
    "ticker_match_status",
    "ticker_match_method",
    "ticker_match_confidence",
    "ticker_match_reason",
    "matched_text",
    "related_tickers",
    "raw_feed_ticker",
    "raw_source_id",
]
NEWS_RSS_STALE_AFTER = timedelta(minutes=60)


def write_news_frame(path: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    output = _with_schema_defaults(frame)
    if path.exists():
        output = pd.concat(
            [_with_schema_defaults(pd.read_parquet(path)), output],
            ignore_index=True,
        )
    output = (
        output.drop_duplicates(subset=["source_id"], keep="last")
        .sort_values(["timestamp_as_of", "ticker", "source_id"], na_position="last")
        .reset_index(drop=True)
    )
    output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
    return len(frame)


def write_manifest(
    manifest_path: Path,
    parquet_path: Path,
    *,
    fetched_at: datetime,
    resolution_min_confidence: float = 0.70,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _stats(parquet_path)
    manifest = {
        "dataset": "news_rss",
        "path": parquet_path.name,
        "schema_version": 2,
        "row_count": stats["row_count"],
        "resolved_row_count": stats["resolved_row_count"],
        "unresolved_row_count": stats["unresolved_row_count"],
        "ambiguous_row_count": stats["ambiguous_row_count"],
        "ticker_count": stats["ticker_count"],
        "resolution_min_confidence": resolution_min_confidence,
        "checksum": _checksum(parquet_path),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": (fetched_at + NEWS_RSS_STALE_AFTER).isoformat(),
        "source_url": None,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _stats(path: Path) -> dict[str, int | str]:
    if not path.exists():
        now = datetime.now(UTC).isoformat()
        return {
            "row_count": 0,
            "resolved_row_count": 0,
            "unresolved_row_count": 0,
            "ambiguous_row_count": 0,
            "ticker_count": 0,
            "max_timestamp_as_of": now,
        }
    frame = _with_schema_defaults(pd.read_parquet(path))
    max_date = pd.to_datetime(frame["timestamp_as_of"]).max().to_pydatetime()
    if max_date.tzinfo is None or max_date.utcoffset() is None:
        max_date = max_date.replace(tzinfo=UTC)
    status = frame["ticker_match_status"].fillna("")
    tickers = frame["ticker"].dropna().astype(str)
    tickers = tickers[tickers.str.strip() != ""]
    return {
        "row_count": len(frame),
        "resolved_row_count": int((status == "resolved").sum()),
        "unresolved_row_count": int((status == "unresolved").sum()),
        "ambiguous_row_count": int((status == "ambiguous").sum()),
        "ticker_count": int(tickers.str.upper().nunique()),
        "max_timestamp_as_of": max_date.isoformat(),
    }


def _with_schema_defaults(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "ticker" not in output.columns:
        output["ticker"] = None
    if "source_id" not in output.columns:
        output["source_id"] = None

    ticker_text = output["ticker"].map(_clean_text)
    has_ticker = ticker_text.notna()

    _fill_missing(
        output,
        "ticker_match_status",
        has_ticker.map({True: "feed_ticker", False: "unresolved"}),
    )
    status_text = output["ticker_match_status"].map(_clean_text)
    _fill_missing(output, "ticker_match_method", has_ticker.map({True: "feed_ticker", False: None}))
    _fill_missing(output, "ticker_match_confidence", has_ticker.map({True: 1.0, False: 0.0}))
    _fill_missing(
        output,
        "ticker_match_reason",
        has_ticker.map(
            {
                True: "Legacy ticker-specific RSS row.",
                False: "Legacy generic RSS row without ticker resolution metadata.",
            }
        ),
    )
    _fill_missing(output, "matched_text", ticker_text)
    _fill_missing(output, "related_tickers", ticker_text.fillna(""))
    raw_feed_ticker_default = pd.Series(
        [
            ticker if status == "feed_ticker" else None
            for ticker, status in zip(ticker_text, status_text, strict=True)
        ],
        index=output.index,
        dtype="object",
    )
    _fill_missing(output, "raw_feed_ticker", raw_feed_ticker_default)
    _fill_missing(output, "raw_source_id", output["source_id"])

    for column in NEWS_COLUMNS:
        if column not in output.columns:
            output[column] = None
    return output[NEWS_COLUMNS].copy()


def _fill_missing(frame: pd.DataFrame, column: str, values: Any) -> None:
    if column not in frame.columns:
        frame[column] = values
        return
    missing = frame[column].isna()
    if missing.any():
        replacement = values[missing] if hasattr(values, "__getitem__") else values
        frame.loc[missing, column] = replacement


def _clean_text(value: object) -> str | None:
    if value is None or pd.isna(value):  # type: ignore[call-overload]
        return None
    text = str(value).strip()
    return text or None


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        digest.update(path.read_bytes())
    return digest.hexdigest()
