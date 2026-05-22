from __future__ import annotations

from scripts import check_dashboard_live_data_qa as qa
from scripts.check_dashboard_live_data_qa import _empty_result, result_failed


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

    assert result_failed(row) is False


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
