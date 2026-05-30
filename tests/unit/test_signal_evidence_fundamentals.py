from __future__ import annotations

from datetime import date

from agency.runtime.signal_evidence import _fundamentals_evidence

AS_OF = date(2026, 5, 30)


def test_fundamentals_evidence_has_12_cards() -> None:
    payload = _fundamentals_evidence(_row(), _detail(), AS_OF)

    assert len(payload["trigger_cards"]) >= 12
    assert {card["label"] for card in payload["trigger_cards"]} >= {
        "Gross margin",
        "Operating margin",
        "Net margin",
        "FCF margin",
        "ROE",
        "ROA",
        "Leverage",
        "Revenue growth YoY",
        "Net income growth YoY",
        "FCF growth YoY",
        "Trailing P/E",
        "Forward P/E",
        "EPS beat rate",
        "Analyst count",
        "Composite score",
        "Filing period",
    }


def test_headline_includes_filing_period_and_form() -> None:
    payload = _fundamentals_evidence(_row(), _detail(), AS_OF)

    assert "AAPL" in payload["trigger_headline"]
    assert "Q3 2026" in payload["trigger_headline"]
    assert "10-Q" in payload["trigger_headline"]
    assert "+0.29" in payload["trigger_headline"]


def test_positive_net_margin_gets_pass_tone() -> None:
    payload = _fundamentals_evidence(_row(), _detail(net_margin=0.24), AS_OF)

    card = _card(payload, "Net margin")
    assert card["value"] == "+24.0%"
    assert card["tone"] == "pass"


def test_negative_revenue_growth_gets_block_tone() -> None:
    payload = _fundamentals_evidence(_row(), _detail(revenue_growth_yoy=-0.09), AS_OF)

    card = _card(payload, "Revenue growth YoY")
    assert card["value"] == "-9.0%"
    assert card["tone"] == "block"


def test_missing_forward_data_shows_plain_language_status() -> None:
    detail = _detail(
        forward_pe=None,
        forward_eps=None,
        eps_beat_rate=None,
        analyst_count=None,
        forward_data_status="not_configured",
        forward_data_as_of=None,
    )

    payload = _fundamentals_evidence(_row(), detail, AS_OF)

    assert "Forward fundamentals not configured" in payload["trigger_detail"]
    assert _card(payload, "Forward P/E")["value"] == "n/a"
    assert _card(payload, "Analyst count")["value"] == "n/a"


def _row() -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "lane_key": "fundamentals",
        "lane": "Fundamentals",
        "signal_as_of": "2026-05-30T12:00:00+00:00",
        "timestamp_as_of": "2026-05-30T12:00:00+00:00",
    }


def _detail(**overrides: object) -> dict[str, object]:
    detail = {
        "filing_period": "Q3",
        "filing_year": 2026,
        "filing_form": "10-Q",
        "filing_period_end": "2026-09-30",
        "period_alignment_status": "aligned",
        "quality_score": 0.42,
        "growth_score": 0.31,
        "valuation_score": -0.10,
        "forward_score": 0.18,
        "composite_score": 0.29,
        "gross_margin": 0.44,
        "operating_margin": 0.30,
        "net_margin": 0.24,
        "fcf_margin": 0.27,
        "roe": 1.47,
        "roa": 0.31,
        "leverage": 0.85,
        "revenue_growth_yoy": 0.09,
        "net_income_growth_yoy": 0.12,
        "fcf_growth_yoy": 0.10,
        "trailing_pe": 28.1,
        "forward_pe": 24.3,
        "forward_eps": 7.28,
        "eps_beat_rate": 0.75,
        "analyst_count": 47,
        "forward_data_status": "ready",
        "forward_data_as_of": "2026-05-30T08:00:00+00:00",
    }
    detail.update(overrides)
    return detail


def _card(payload: dict[str, object], label: str) -> dict[str, str]:
    cards = payload["trigger_cards"]
    assert isinstance(cards, list)
    for card in cards:
        if isinstance(card, dict) and card.get("label") == label:
            return card
    raise AssertionError(f"missing card: {label}")
