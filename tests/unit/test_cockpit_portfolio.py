from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_portfolio_position_pl_is_derived_from_prices() -> None:
    sources = _sample_sources()
    sources["portfolio"]["positions"][0].pop("unrealized_pl_pct")  # type: ignore[index]
    sources["portfolio"]["positions"][0]["entry_price"] = 40.0  # type: ignore[index]
    sources["portfolio"]["positions"][0]["stop_price"] = 38.0  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    position = context["positions"][0]

    assert position["pl_pct"] == 6.25
    assert position["stop_distance_pct"] == 10.59


def test_capacity_gross_post_trade_uses_staged_orders() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["account"]["gross_exposure"] == 32.5
    assert context["account"]["gross_post_trade"] == 36.7


def test_zero_position_portfolio_has_explicit_empty_state() -> None:
    sources = _sample_sources()
    sources["portfolio"]["positions"] = []  # type: ignore[index]

    context = cockpit_context_from_sources(sources)

    assert context["portfolio_phase"]["empty_state"] == (
        "No open paper positions are reported by the broker for this cycle."
    )


def test_portfolio_phase_starts_with_bluf_sentence() -> None:
    html = _template()

    assert "Review current positions before clearing today's manifest." in html
    assert html.index("Review current positions before clearing today's manifest.") < html.index(
        "cockpit-position-table"
    )


def test_close_candidate_requires_keep_or_close_before_clearance() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["clearance"]["requires_position_decisions"] is True
    assert context["positions"][0]["decision_controls"] == ["keep", "close"]


def test_capacity_warning_names_rule_value_and_user_action() -> None:
    sources = _sample_sources()
    sources["dashboard"]["policy_summary"]["max_gross_exposure_pct"] = 35  # type: ignore[index]

    context = cockpit_context_from_sources(sources)

    assert context["account"]["capacity_warning"] == (
        "Gross exposure would be 36.7% versus the 35.0% cap. Reduce staged buys or close exposure before clearance."
    )


def test_capacity_thresholds_have_whymark_tips() -> None:
    html = _template()

    assert "data-cockpit-tip=\"gross-exposure-threshold\"" in html
    assert "data-cockpit-tip=\"sector-exposure-threshold\"" in html
    assert "data-cockpit-tip=\"cash-reserve-threshold\"" in html
