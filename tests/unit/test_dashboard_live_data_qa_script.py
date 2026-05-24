from __future__ import annotations

from pathlib import Path

from scripts import check_dashboard_live_data_qa as qa
from scripts.check_dashboard_live_data_qa import _empty_result, result_failed

QA_SCRIPT = Path("scripts/check_dashboard_live_data_qa.py")
EXPECTED_QA_ROUTES = {
    "/",
    "/command",
    "/signals",
    "/market-regime",
    "/final-selection",
    "/risk",
    "/execution-preview",
    "/portfolio-monitor",
    "/learning",
    "/audit",
    "/policy",
    "/candidates/NVDA",
}


def _ready_payload_for(url: str):
    if url.endswith("/status/full-live-readiness"):
        return {
            "ready": True,
            "tradable_ready": True,
            "verdict": "ready_for_full_live_cycle",
        }
    if url.endswith("/status/data-load"):
        return {
            "status_class": "pass",
            "tradable_ready": True,
            "warnings": [],
            "health_monitor": {"status": "healthy", "reliable": True},
        }
    if url.endswith("/status/data-sources"):
        return [{"source": "daily-market-bars", "status": "HEALTHY"}]
    if url.endswith("/reports/selection"):
        return [{"cycle_id": "cycle-1", "ticker": "AAPL"}]
    if url.endswith("/risk/decisions"):
        return [{"cycle_id": "cycle-1", "ticker": "AAPL", "decision": "WARN"}]
    raise AssertionError(url)


def test_dashboard_live_data_qa_result_passes_with_health_rows() -> None:
    row = _empty_result("desktop", "/signals")
    row["health_visible"] = True
    row["health_panel_count"] = 1
    row["health_rows_count"] = 2
    row["v3_build_served"] = True
    row["v3_screen_class"] = True
    row["v3_universal_briefing"] = True
    row["v3_briefing_visible"] = True
    row["v3_briefing_text"] = "Signal evidence. Inspect lane support. Signal rows include proof."

    assert result_failed(row) is False


def test_dashboard_live_data_qa_accepts_cockpit_lane_state_as_root_health_proof() -> None:
    row = _empty_result("mobile", "/")
    row["cockpit_data_state_visible"] = True
    row["cockpit_lane_rows_count"] = 3
    row["v3_build_served"] = True
    row["v3_screen_class"] = True
    row["v3_universal_briefing"] = True
    row["v3_briefing_visible"] = False
    row["v3_briefing_text"] = ""

    assert result_failed(row) is False


def test_dashboard_live_data_qa_rejects_cockpit_lane_state_on_non_cockpit_route() -> None:
    row = _empty_result("mobile", "/signals")
    row["cockpit_data_state_visible"] = True
    row["cockpit_lane_rows_count"] = 3
    row["v3_build_served"] = True
    row["v3_screen_class"] = True
    row["v3_universal_briefing"] = True
    row["v3_briefing_visible"] = True
    row["v3_briefing_text"] = "Signal evidence. Inspect lane support. Signal rows include proof."

    assert result_failed(row) is True


def test_dashboard_live_data_qa_cockpit_lane_probe_accepts_row_count_progress() -> None:
    script = QA_SCRIPT.read_text(encoding="utf-8")

    assert "progressText.trim().length > 0" in script
    assert "No lane action recorded" in script


def test_dashboard_live_data_qa_checks_cockpit_root_and_command_route() -> None:
    assert qa.PAGES[0] == "/"
    assert set(qa.PAGES) == EXPECTED_QA_ROUTES


def test_dashboard_live_data_qa_fails_on_default_v3_briefing_copy() -> None:
    row = _empty_result("desktop", "/risk")
    row["health_visible"] = True
    row["health_panel_count"] = 1
    row["health_rows_count"] = 2
    row["v3_build_served"] = True
    row["v3_screen_class"] = True
    row["v3_universal_briefing"] = True
    row["v3_briefing_visible"] = True
    row["v3_briefing_text"] = (
        "BLUF Risk Operator move Pre-flight review Evidence "
        "This screen must show current source proof"
    )

    assert result_failed(row) is True


def test_dashboard_live_data_qa_result_fails_on_page_error() -> None:
    row = _empty_result("mobile", "/signals")
    row["page_error"] = "TimeoutError: page did not finish loading"

    assert result_failed(row) is True


def test_dashboard_live_data_qa_result_fails_on_operational_readiness_gap() -> None:
    row = _empty_result("desktop", "/")
    row["health_visible"] = True
    row["health_panel_count"] = 1
    row["health_rows_count"] = 2
    row["operational_readiness_failures"] = ["full-live tradable_ready=false"]

    assert result_failed(row) is True


def test_dashboard_live_data_qa_result_fails_when_v3_build_is_not_served() -> None:
    row = _empty_result("desktop", "/final-selection")
    row["health_visible"] = True
    row["health_panel_count"] = 1
    row["health_rows_count"] = 2
    row["v3_build_served"] = False
    row["v3_screen_class"] = True
    row["v3_universal_briefing"] = True
    row["v3_briefing_visible"] = True

    assert result_failed(row) is True


def test_dashboard_live_data_qa_result_fails_when_non_cockpit_briefing_is_missing() -> None:
    row = _empty_result("desktop", "/risk")
    row["health_visible"] = True
    row["health_panel_count"] = 1
    row["health_rows_count"] = 2
    row["v3_build_served"] = True
    row["v3_screen_class"] = True
    row["v3_universal_briefing"] = False
    row["v3_briefing_visible"] = False

    assert result_failed(row) is True


def test_dashboard_live_data_qa_forbidden_terms_use_word_boundaries() -> None:
    text = "LLM demoted this setup, but it did not expose demo data."

    assert qa._forbidden_term_hits("LLM demoted this setup") == []
    assert qa._forbidden_term_hits(text) == ["demo"]


def test_dashboard_live_data_qa_page_load_retries_transient_timeout(monkeypatch) -> None:
    class FakeLocator:
        def wait_for(self, **_kwargs):
            return None

        def inner_text(self, **_kwargs) -> str:
            return "Live data health"

    class FakePage:
        attempts = 0
        retried = False

        def goto(self, *_args, **_kwargs) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transient timeout")

        def locator(self, selector: str) -> FakeLocator:
            assert selector == "body"
            return FakeLocator()

        def wait_for_timeout(self, milliseconds: int) -> None:
            assert milliseconds == qa.PAGE_RETRY_DELAY_MS
            self.retried = True

    monkeypatch.setattr(qa, "PlaywrightError", RuntimeError)

    page = FakePage()

    assert qa._load_page_body(page, "http://unit.test/signals") == "Live data health"
    assert page.attempts == 2
    assert page.retried is True


def test_dashboard_live_data_qa_json_get_accepts_endpoint_lists(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'[{"source":"daily-market-bars","status":"HEALTHY"}]'

    monkeypatch.setattr(qa, "urlopen", lambda *_args, **_kwargs: Response())

    assert qa._json_get("http://unit.test/status/data-sources") == [
        {"source": "daily-market-bars", "status": "HEALTHY"}
    ]


def test_dashboard_live_data_qa_json_get_retries_cold_endpoint_timeout(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'[{"cycle_id":"cycle-1","ticker":"AAPL"}]'

    attempts = {"count": 0}

    def fake_urlopen(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("cold endpoint startup")
        return Response()

    monkeypatch.setattr(qa, "urlopen", fake_urlopen)

    assert qa._json_get("http://unit.test/reports/selection") == [
        {"cycle_id": "cycle-1", "ticker": "AAPL"}
    ]
    assert attempts["count"] == 2


def test_dashboard_live_data_qa_allows_context_only_data_load_warnings(monkeypatch) -> None:
    def fake_json_get(url: str):
        if url.endswith(("/reports/selection", "/risk/decisions")):
            return _ready_payload_for(url)
        if url.endswith("/status/full-live-readiness"):
            return {
                "ready": True,
                "tradable_ready": True,
                "verdict": "ready_for_full_live_cycle",
            }
        if url.endswith("/status/data-load"):
            return {
                "status_class": "warn",
                "tradable_ready": True,
                "warnings": [
                    {"kind": "dataset", "item": "news_rss", "reason": "context proof aging"},
                    {"kind": "agent_lane", "item": "news", "reason": "context proof aging"},
                ],
                "health_monitor": {"status": "healthy", "reliable": True},
            }
        if url.endswith("/status/data-sources"):
            return [{"source": "daily-market-bars", "status": "HEALTHY"}]
        raise AssertionError(url)

    monkeypatch.setattr(qa, "_json_get", fake_json_get)

    assert qa._operational_readiness_failures("http://unit.test") == []


def test_dashboard_live_data_qa_allows_nonblocking_trade_progress_warning(monkeypatch) -> None:
    def fake_json_get(url: str):
        if url.endswith(("/reports/selection", "/risk/decisions")):
            return _ready_payload_for(url)
        if url.endswith("/status/full-live-readiness"):
            return {
                "ready": True,
                "tradable_ready": True,
                "verdict": "ready_for_full_live_cycle",
            }
        if url.endswith("/status/data-load"):
            return {
                "status_class": "warn",
                "tradable_ready": True,
                "warnings": [
                    {
                        "kind": "data_refresh",
                        "item": "stock_trades",
                        "reason": "18 ticker(s) can pass forward now.",
                    }
                ],
                "market_flow_summary": {
                    "status": "ready",
                    "usable_ticker_count": 168,
                    "signal_ticker_count": 168,
                    "expected_ticker_count": 168,
                },
                "health_monitor": {"status": "context_stale", "reliable": True},
            }
        if url.endswith("/status/data-sources"):
            return [{"source": "daily-market-bars", "status": "HEALTHY"}]
        raise AssertionError(url)

    monkeypatch.setattr(qa, "_json_get", fake_json_get)

    assert qa._operational_readiness_failures("http://unit.test") == []


def test_dashboard_live_data_qa_allows_review_subset_mode(monkeypatch) -> None:
    def fake_json_get(url: str):
        if url.endswith(("/reports/selection", "/risk/decisions")):
            return _ready_payload_for(url)
        if url.endswith("/status/full-live-readiness"):
            return {
                "ready": False,
                "review_operational_ready": True,
                "tradable_ready": False,
                "verdict": "ready_with_partial_lanes",
                "blocker_count": 0,
            }
        if url.endswith("/status/data-load"):
            return {
                "ready": True,
                "review_operational_ready": True,
                "status_class": "warn",
                "blocker_count": 0,
                "warnings": [{"kind": "dataset", "item": "stock_trades"}],
                "health_monitor": {"status": "healthy", "reliable": True},
            }
        if url.endswith("/status/data-sources"):
            return [{"source": "daily-market-bars", "status": "HEALTHY"}]
        raise AssertionError(url)

    monkeypatch.setattr(qa, "_json_get", fake_json_get)

    assert (
        qa._operational_readiness_failures(
            "http://unit.test",
            readiness_scope="review-subset",
        )
        == []
    )


def test_dashboard_live_data_qa_full_mode_rejects_review_subset(monkeypatch) -> None:
    def fake_json_get(url: str):
        if url.endswith(("/reports/selection", "/risk/decisions")):
            return _ready_payload_for(url)
        if url.endswith("/status/full-live-readiness"):
            return {
                "ready": False,
                "review_operational_ready": True,
                "tradable_ready": False,
                "verdict": "ready_with_partial_lanes",
                "blocker_count": 0,
            }
        if url.endswith("/status/data-load"):
            return {
                "ready": True,
                "review_operational_ready": True,
                "status_class": "warn",
                "blocker_count": 0,
                "warnings": [],
                "health_monitor": {"status": "healthy", "reliable": True},
            }
        if url.endswith("/status/data-sources"):
            return [{"source": "daily-market-bars", "status": "HEALTHY"}]
        raise AssertionError(url)

    monkeypatch.setattr(qa, "_json_get", fake_json_get)

    failures = qa._operational_readiness_failures("http://unit.test")

    assert "full-live ready=False" in failures
    assert "full-live tradable_ready=False" in failures


def test_dashboard_live_data_qa_rejects_runtime_api_fallback_payloads(monkeypatch) -> None:
    def fake_json_get(url: str):
        if url.endswith("/reports/selection"):
            return [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "runtime_origin": "runtime_artifact_fallback",
                }
            ]
        return _ready_payload_for(url)

    monkeypatch.setattr(qa, "_json_get", fake_json_get)

    failures = qa._operational_readiness_failures("http://unit.test")

    assert (
        "/reports/selection contains non-operational token 'runtime_artifact_fallback'"
        in failures
    )


def test_dashboard_live_data_qa_rejects_runtime_api_test_payloads(monkeypatch) -> None:
    def fake_json_get(url: str):
        if url.endswith("/risk/decisions"):
            return [
                {
                    "cycle_id": "manual-smoke-risk",
                    "ticker": "AAPL",
                    "decision": "WARN",
                }
            ]
        return _ready_payload_for(url)

    monkeypatch.setattr(qa, "_json_get", fake_json_get)

    failures = qa._operational_readiness_failures("http://unit.test")

    assert "/risk/decisions contains non-operational token 'manual-smoke'" in failures
