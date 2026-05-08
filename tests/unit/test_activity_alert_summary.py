from __future__ import annotations

import pandas as pd
from activity_alerts.summary import build_activity_alert_summary, summary_to_markdown

EXPECTED_TICKER_COUNT = 2
EXPECTED_TOTAL_NOTIONAL = 3_000_000.0


def test_build_activity_alert_summary_reports_provider_coverage() -> None:
    summary = build_activity_alert_summary(
        pd.DataFrame(
            [
                _row("AAPL", "block_trade", "BULLISH", notional=1_000_000.0),
                _row("MSFT", "dark_pool", "BEARISH", notional=2_000_000.0),
            ]
        ),
        rows_written=2,
    )

    assert summary["verdict"] == "ready_for_research_batch"
    assert summary["ticker_count"] == EXPECTED_TICKER_COUNT
    assert summary["alert_type_counts"] == {"block_trade": 1, "dark_pool": 1}
    assert summary["direction_counts"] == {"BEARISH": 1, "BULLISH": 1}
    assert summary["total_notional"] == EXPECTED_TOTAL_NOTIONAL
    assert summary["issues"] == []


def test_activity_alert_summary_marks_empty_input_blocked() -> None:
    summary = build_activity_alert_summary(pd.DataFrame())

    assert summary["verdict"] == "blocked"
    assert "no activity alert rows" in summary["issues"]


def test_summary_to_markdown_includes_verdict_and_counts() -> None:
    summary = build_activity_alert_summary(pd.DataFrame([_row("AAPL", "block_trade", "BULLISH")]))

    markdown = summary_to_markdown(summary)

    assert "Verdict: `ready_for_research_batch`" in markdown
    assert "| block_trade | 1 |" in markdown


def _row(
    ticker: str,
    alert_type: str,
    direction: str,
    *,
    notional: float = 1_000_000.0,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "alert_type": alert_type,
        "direction": direction,
        "source": "fixture",
        "source_tier": "PAID_SUB_EMAIL",
        "source_id": f"{ticker}-{alert_type}",
        "timestamp_as_of": "2026-05-08T13:00:00+00:00",
        "verification_level": "CONFIRMED",
        "notional": notional,
        "premium": None,
    }
