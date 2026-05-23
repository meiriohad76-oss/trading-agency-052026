from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")
PANELS = Path("src/agency/templates/_cockpit_panels.html")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _panels() -> str:
    return PANELS.read_text(encoding="utf-8")


def test_cockpit_has_all_six_instrument_panels() -> None:
    html = _panels()

    for panel in (
        "cockpit-panel-universe",
        "cockpit-panel-signals",
        "cockpit-panel-audit",
        "cockpit-panel-policy",
        "cockpit-panel-monitor",
        "cockpit-panel-ticker-detail",
    ):
        assert panel in html


def test_instrument_nav_has_five_buttons_and_excludes_ticker_detail() -> None:
    html = _template()

    assert html.count("data-cockpit-panel-target=") == 5
    assert 'data-cockpit-panel-target="ticker-detail"' not in html


def test_ticker_detail_opens_from_ticker_click() -> None:
    html = _template()

    assert "data-cockpit-ticker-detail" in html
    assert "data-cockpit-ticker-payload" in html


def test_universe_panel_uses_source_health_rows() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["sources"][0]["name"] == "Massive live trade slices"
    assert "source in sources" in _panels()


def test_universe_panel_has_expert_stat_grid_source_table_blocked_and_pit_sections() -> None:
    html = _panels()

    assert "cockpit-panel-stat-grid" in html
    assert "Data sources" in html
    assert "Blocked tickers" in html
    assert "PIT integrity" in html
    assert "source.coverage" in html
    assert "universe_blocked" in html


def test_signals_panel_explains_tier_ladder() -> None:
    html = _panels()

    assert "Confirmed means a direct production source supplied the value." in html
    assert "Suppressed means the signal is retained for audit but not allowed to drive the decision." in html


def test_signals_panel_has_filters_rule_cards_and_signal_log() -> None:
    html = _panels()

    assert "cockpit-filter-chip" in html
    assert "confirmed" in html
    assert "inferred" in html
    assert "suppressed" in html
    assert "Evidence treatment rule" in html
    assert "Breadth rule" in html
    assert "Signal log" in html


def test_ticker_panel_shows_llm_rationale_or_not_run_reason() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    rows = {row["ticker"]: row for row in context["candidates"]}

    assert rows["AAA"]["llm_rationale"] == "LLM not run for this ticker"
    assert "data-ticker-llm-rationale" in _panels()


def test_ticker_panel_has_rich_evidence_targets() -> None:
    html = _panels()
    script = Path("src/agency/static/cockpit.js").read_text(encoding="utf-8")
    template = _template()

    for target in (
        "data-ticker-headline",
        "data-ticker-next-step",
        "data-ticker-data-health",
        "data-ticker-support",
        "data-ticker-caution",
        "data-ticker-signals",
        "data-ticker-detail-link",
    ):
        assert target in html
    assert "/api/cockpit/ticker/" in script
    assert "#cockpit-panel-ticker-detail" in script
    assert "ux-v3-rich-ticker-detail-20260522" in template


def test_audit_panel_shows_cycle_and_evidence_hash_when_available() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"][0]["evidence_hash"] = "hash-bbb"  # type: ignore[index]
    context = cockpit_context_from_sources(sources)

    assert context["audit_lifecycle"]["cycle_id"] == "cycle-live-20260522-1530"
    assert context["audit_lifecycle"]["traces"]["BBB"][0]["evidence_hash"] == "hash-bbb"
    assert "evidence hash" in _panels().lower()


def test_audit_panel_uses_timeline_and_reproducibility_note() -> None:
    html = _panels()

    assert "cockpit-audit-timeline" in html
    assert "state transitions are deterministic" in html
    assert "evidence pack hash" in html.lower()


def test_policy_panel_locks_live_trading() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["policy"]["live_trading"] == "locked off"
    assert "Live trading is locked off" in _panels()


def test_monitor_panel_has_live_or_last_event_timestamp() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["monitor_events"][0]["timestamp"] == "after close"
    assert "event.timestamp" in _panels()


def test_monitor_panel_has_filter_chips_and_live_indicator() -> None:
    html = _panels()

    assert "data-monitor-filter=\"all\"" in html
    assert "data-monitor-filter=\"warn\"" in html
    assert "data-monitor-filter=\"block\"" in html
    assert "data-cockpit-monitor-live" in html
