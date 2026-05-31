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


def test_fundamentals_evidence_explains_drivers_trend_and_meaning() -> None:
    detail = _detail(
        composite_score=-0.78,
        quality_score=-0.62,
        growth_score=-0.91,
        net_margin=0.168,
        fcf_margin=-0.87,
        leverage=0.92,
        revenue_growth_yoy=-0.05,
        net_income_growth_yoy=0.11,
        fcf_growth_yoy=-0.64,
    )

    payload = _fundamentals_evidence(_row(ticker="C"), detail, AS_OF)

    assert "C fundamentals are bearish" in payload["trigger_headline"]
    assert "FCF margin -87.0%" in payload["trigger_headline"]
    assert "leverage +92.0%" in payload["trigger_headline"]
    assert "net margin +16.8%" in payload["trigger_headline"]
    assert "Revenue decreased 5.0%" in payload["trigger_detail"]
    assert "free cash flow decreased 64.0%" in payload["trigger_detail"]

    drivers = _card(payload, "Main drivers")
    assert "cash burn" in drivers["detail"]
    assert "high leverage" in drivers["detail"]
    assert "profitable net margin" in drivers["detail"]

    trend = _card(payload, "YoY trend")
    assert trend["value"] == "revenue -5.0%"
    assert "Revenue decreased 5.0%" in trend["detail"]
    assert "net income increased 11.0%" in trend["detail"]

    assert "bearish because free cash flow is negative" in _card(payload, "FCF margin")["detail"]
    assert "bearish when high" in _card(payload, "Leverage")["detail"]


def test_fundamentals_metric_cards_explain_sign_and_user_meaning() -> None:
    payload = _fundamentals_evidence(_row(ticker="MSFT"), _detail(), AS_OF)

    expected_fragments = {
        "Gross margin": "bullish because higher gross margin",
        "Operating margin": "bullish because core operations",
        "Net margin": "bullish because net income is positive",
        "FCF margin": "bullish because operations generated cash",
        "ROE": "bullish because equity generated profit",
        "ROA": "bullish because assets generated profit",
        "Leverage": "caution because liabilities are",
        "Trailing P/E": "valuation caution",
        "Forward P/E": "forward valuation caution",
        "EPS beat rate": "bullish execution quality",
        "Analyst count": "reliability input, not a bullish or bearish signal by itself",
        "Composite score": "bullish composite",
        "Filing period": "official SEC filing context, not directional by itself",
    }

    for label, fragment in expected_fragments.items():
        assert fragment in _card(payload, label)["detail"]


def test_fundamentals_metric_cards_explain_missing_and_negative_meaning() -> None:
    detail = _detail(
        gross_margin=-0.12,
        operating_margin=-0.08,
        net_margin=-0.03,
        roe=-0.15,
        roa=-0.04,
        leverage=0.18,
        trailing_pe=44.0,
        forward_pe=None,
        eps_beat_rate=0.25,
        analyst_count=0,
        composite_score=-0.44,
        forward_data_status="missing",
    )

    payload = _fundamentals_evidence(_row(ticker="XYZ"), detail, AS_OF)

    assert "bearish because negative gross margin" in _card(payload, "Gross margin")["detail"]
    assert "bearish because core operations lost money" in _card(
        payload,
        "Operating margin",
    )["detail"]
    assert "bearish because negative net margin" in _card(payload, "Net margin")["detail"]
    assert "bearish because equity generated losses" in _card(payload, "ROE")["detail"]
    assert "bullish balance-sheet input" in _card(payload, "Leverage")["detail"]
    assert "bearish valuation input" in _card(payload, "Trailing P/E")["detail"]
    assert "forward valuation input is not used" in _card(payload, "Forward P/E")["detail"]
    assert "bearish execution quality" in _card(payload, "EPS beat rate")["detail"]
    assert "forward valuation is not independently covered" in _card(
        payload,
        "Analyst count",
    )["detail"]
    assert "bearish composite" in _card(payload, "Composite score")["detail"]


def _row(*, ticker: str = "AAPL") -> dict[str, object]:
    return {
        "ticker": ticker,
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
