from __future__ import annotations

from agency.runtime.readiness_sources import relevant_source_health, used_sources


def test_relevant_source_health_keeps_degraded_configured_sources_without_signals() -> None:
    rows = [
        {"source": "daily-market-bars", "status": "HEALTHY", "freshness": "FRESH"},
        {"source": "subscription-email-thesis", "status": "UNAVAILABLE", "freshness": "UNAVAILABLE"},
        {"source": "news-rss", "status": "HEALTHY", "freshness": "FRESH"},
    ]

    relevant = relevant_source_health(rows, used_sources={"daily-market-bars"})

    assert [row["source"] for row in relevant] == [
        "daily-market-bars",
        "subscription-email-thesis",
    ]


def test_used_sources_maps_dataset_provenance_to_source_health_names() -> None:
    reports = [
        {
            "evidence_pack": {
                "actionable_signals": [
                    {"provenance": {"source": "stock_trades"}},
                    {"provenance": {"source": "prices_daily"}},
                ]
            }
        }
    ]

    assert used_sources(reports) == {"massive-stock-trades", "daily-market-bars"}
