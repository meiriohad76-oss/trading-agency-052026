from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from research.scripts.resolve_existing_news_rss import main, repair_existing_news_rss

FETCHED_AT = datetime(2026, 5, 7, 8, 0, tzinfo=UTC)
RESOLVED_CONFIDENCE = 0.88


def test_resolve_existing_news_rss_updates_unresolved_generic_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "input.parquet"
    output_path = tmp_path / "resolved.parquet"
    manifest_path = tmp_path / "resolved.json"
    alias_path = _alias_path(tmp_path)
    _write_input(
        input_path,
        [
            _news_row(
                title="Apple Inc. announces AI supplier expansion",
                url="https://example.test/apple-ai",
                source_id="rss-raw:apple",
            ),
            _news_row(
                title="Global futures rise before central bank remarks",
                url="https://example.test/global-futures",
                source_id="rss-raw:global",
            ),
        ],
    )

    summary = repair_existing_news_rss(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest_path,
        ticker_aliases_path=alias_path,
        tickers=("AAPL", "MSFT"),
        min_confidence=0.7,
        dry_run=False,
        clock=lambda: FETCHED_AT,
    )

    frame = pd.read_parquet(output_path).sort_values("title").reset_index(drop=True)
    apple = frame[frame["ticker"] == "AAPL"].iloc[0]
    unresolved = frame[frame["ticker_match_status"] == "unresolved"].iloc[0]

    assert summary.raw_rows_scanned == 2
    assert summary.newly_resolved_rows == 1
    assert apple["ticker_match_method"] == "legal_name"
    assert apple["ticker_match_confidence"] == RESOLVED_CONFIDENCE
    assert apple["matched_text"] == "Apple Inc."
    assert "Legal-name alias" in apple["ticker_match_reason"]
    assert pd.isna(apple["raw_feed_ticker"])
    assert apple["raw_source_id"] == "rss-raw:apple"
    assert pd.isna(unresolved["ticker"])
    assert unresolved["raw_source_id"] == "rss-raw:global"


def test_resolve_existing_news_rss_uses_massive_reference_names(tmp_path: Path) -> None:
    input_path = tmp_path / "input.parquet"
    output_path = tmp_path / "resolved.parquet"
    manifest_path = tmp_path / "resolved.json"
    reference_path = tmp_path / "massive_ticker_details.json"
    reference_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "ticker": "PLTR",
                        "name": "Palantir Technologies Inc. Class A Common Stock",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_input(
        input_path,
        [
            _news_row(
                title="Palantir announces new AI platform contract",
                url="https://example.test/palantir-ai",
                source_id="rss-raw:palantir",
            ),
        ],
    )

    repair_existing_news_rss(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest_path,
        ticker_aliases_path=None,
        reference_details_path=reference_path,
        tickers=("PLTR",),
        min_confidence=0.7,
        dry_run=False,
        clock=lambda: FETCHED_AT,
    )

    frame = pd.read_parquet(output_path)
    row = frame.iloc[0]
    assert row["ticker"] == "PLTR"
    assert row["ticker_match_method"] == "brand_alias"
    assert row["matched_text"] == "Palantir"


def test_resolve_existing_news_rss_is_idempotent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.parquet"
    first_output = tmp_path / "resolved-1.parquet"
    second_output = tmp_path / "resolved-2.parquet"
    alias_path = _alias_path(tmp_path)
    _write_input(
        input_path,
        [
            _news_row(
                title="Apple Inc. announces AI supplier expansion",
                url="https://example.test/apple-ai",
                source_id="rss-raw:apple",
            ),
            _news_row(
                title="Global futures rise before central bank remarks",
                url="https://example.test/global-futures",
                source_id="rss-raw:global",
            ),
        ],
    )

    repair_existing_news_rss(
        input_path=input_path,
        output_path=first_output,
        manifest_path=tmp_path / "resolved-1.json",
        ticker_aliases_path=alias_path,
        tickers=("AAPL", "MSFT"),
        min_confidence=0.7,
        dry_run=False,
        clock=lambda: FETCHED_AT,
    )
    second_summary = repair_existing_news_rss(
        input_path=first_output,
        output_path=second_output,
        manifest_path=tmp_path / "resolved-2.json",
        ticker_aliases_path=alias_path,
        tickers=("AAPL", "MSFT"),
        min_confidence=0.7,
        dry_run=False,
        clock=lambda: FETCHED_AT,
    )

    first = pd.read_parquet(first_output).sort_values("source_id").reset_index(drop=True)
    second = pd.read_parquet(second_output).sort_values("source_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(first, second)
    assert second_summary.newly_resolved_rows == 0


def test_resolve_existing_news_rss_writes_manifest_coverage(tmp_path: Path) -> None:
    input_path = tmp_path / "input.parquet"
    output_path = tmp_path / "resolved.parquet"
    manifest_path = tmp_path / "resolved.json"
    alias_path = _alias_path(tmp_path)
    _write_input(
        input_path,
        [
            _news_row(
                title="Apple Inc. announces AI supplier expansion",
                url="https://example.test/apple-ai",
                source_id="rss-raw:apple",
            ),
            _news_row(
                title="Global futures rise before central bank remarks",
                url="https://example.test/global-futures",
                source_id="rss-raw:global",
            ),
        ],
    )

    repair_existing_news_rss(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest_path,
        ticker_aliases_path=alias_path,
        tickers=("AAPL", "MSFT"),
        min_confidence=0.7,
        dry_run=False,
        clock=lambda: FETCHED_AT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset"] == "news_rss"
    assert manifest["schema_version"] == 2
    assert manifest["row_count"] == 2
    assert manifest["resolved_row_count"] == 1
    assert manifest["unresolved_row_count"] == 1
    assert manifest["ticker_count"] == 1
    assert manifest["resolution_min_confidence"] == 0.7


def test_resolve_existing_news_rss_dry_run_prints_coverage_without_writing(
    tmp_path: Path,
    capsys,
) -> None:
    input_path = tmp_path / "input.parquet"
    output_path = tmp_path / "resolved.parquet"
    manifest_path = tmp_path / "resolved.json"
    alias_path = _alias_path(tmp_path)
    _write_input(
        input_path,
        [
            _news_row(
                title="Apple Inc. announces AI supplier expansion",
                url="https://example.test/apple-ai",
                source_id="rss-raw:apple",
            ),
            _news_row(
                title="Global futures rise before central bank remarks",
                url="https://example.test/global-futures",
                source_id="rss-raw:global",
            ),
        ],
    )

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--manifest",
            str(manifest_path),
            "--ticker-aliases",
            str(alias_path),
            "--ticker",
            "AAPL",
            "--ticker",
            "MSFT",
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["raw_rows_scanned"] == 2
    assert payload["newly_resolved_rows"] == 1
    assert payload["ambiguous_rows"] == 0
    assert payload["unresolved_rows"] == 1
    assert payload["top_matched_tickers"] == [{"ticker": "AAPL", "rows": 1}]
    assert not output_path.exists()
    assert not manifest_path.exists()


def _write_input(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, engine="pyarrow", compression="snappy", index=False)


def _news_row(*, title: str, url: str, source_id: str) -> dict[str, object]:
    return {
        "ticker": None,
        "feed_url": "https://example.test/rss",
        "feed_name": "Example",
        "title": title,
        "url": url,
        "summary": "",
        "published_at": FETCHED_AT,
        "source": "rss",
        "source_tier": "RSS_HEADLINE",
        "source_id": source_id,
        "source_url": url,
        "timestamp_observed": FETCHED_AT,
        "timestamp_as_of": FETCHED_AT,
        "freshness": "FRESH",
        "confidence": 0.55,
        "verification_level": "CONFIRMED",
    }


def _alias_path(tmp_path: Path) -> Path:
    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps(
            {
                "aliases": [
                    {
                        "ticker": "AAPL",
                        "cik": "0000320193",
                        "legal_names": ["Apple Inc."],
                        "brand_aliases": ["Apple"],
                        "allow_plain_brand": True,
                    },
                    {
                        "ticker": "MSFT",
                        "cik": "0000789019",
                        "legal_names": ["Microsoft Corporation"],
                        "brand_aliases": ["Microsoft"],
                        "allow_plain_brand": True,
                    },
                ],
                "ambiguous_symbols": ["A", "C", "F", "T", "APP", "NOW", "ON"],
            }
        ),
        encoding="utf-8",
    )
    return path
