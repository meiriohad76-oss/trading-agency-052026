from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from html import unescape as html_unescape
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_URL = "http://127.0.0.1:8000/cockpit"
PREFLIGHT_ENDPOINTS = (
    "/api/cockpit",
    "/status/data-load",
    "/status/full-live-readiness",
    "/status/data-sources",
    "/status/execution-preview",
)
PREFLIGHT_REPORT_NAME = "cockpit-preflight.json"
SCENARIOS = ("normal", "no-actionable", "outage", "status-delayed", "submitted")
VIEWPORTS = (
    ("desktop-1920", {"viewport": {"width": 1920, "height": 1080}}),
    ("desktop-1366", {"viewport": {"width": 1366, "height": 768}}),
    ("kiosk-1280", {"viewport": {"width": 1280, "height": 720}}),
    (
        "mobile-390",
        {
            "viewport": {"width": 390, "height": 844},
            "has_touch": True,
            "is_mobile": True,
        },
    ),
)
PANEL_NAMES = ("universe", "signals", "audit", "policy", "monitor")
PAGE_GOTO_TIMEOUT_MS = 60_000
PREFLIGHT_REQUEST_TIMEOUT_SECONDS = 30


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    scenario_names = _scenario_names(args.scenario)

    preflight = _preflight(args.url)
    _validate_paper_submit_preflight(
        preflight,
        allow_paper_submit=args.allow_paper_submit,
    )
    preflight_path = output_dir / PREFLIGHT_REPORT_NAME
    preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True), encoding="utf-8")
    contract_results = _semantic_contract_case_results()
    contract_path = output_dir / "cockpit-first-screen-semantic-contract.json"
    contract_path.write_text(
        json.dumps(contract_results, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for scenario_name in scenario_names:
                target_url = _scenario_url(args.url, scenario_name)
                for viewport_name, profile in VIEWPORTS:
                    console_errors: list[str] = []
                    page_errors: list[str] = []
                    external_requests: list[str] = []
                    page = browser.new_page(
                        viewport=profile["viewport"],
                        has_touch=bool(profile.get("has_touch")),
                        is_mobile=bool(profile.get("is_mobile")),
                    )
                    page.on("console", _console_error_collector(console_errors))
                    page.on("pageerror", _page_error_collector(page_errors))
                    page.on("request", _external_request_collector(external_requests, target_url))
                    result = {
                        "viewport": viewport_name,
                        "url": target_url,
                        "scenario": scenario_name,
                        "focus": args.focus,
                        "http_ok": False,
                        "console_errors": console_errors,
                        "page_errors": page_errors,
                        "external_requests": external_requests,
                        "horizontal_overflow": False,
                        "bluf_visible": False,
                        "phase_visible": False,
                        "candidate_visible": False,
                        "submit_gate_safe": False,
                        "semantic_errors": [],
                        "readability_errors": [],
                        "inner_overflow_errors": [],
                        "panel_screenshots": [],
                        "unreadable_controls": [],
                        "small_touch_targets": [],
                        "screenshot": "",
                        "error": "",
                    }
                    try:
                        response = page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=PAGE_GOTO_TIMEOUT_MS,
                        )
                        result["http_ok"] = response is not None and response.status == 200
                        page.wait_for_selector(".cockpit-bluf", timeout=10_000)
                        page.wait_for_selector(".cockpit-data-state-strip", timeout=10_000)
                        page.wait_for_selector(".cockpit-phase:not([hidden])", timeout=10_000)
                        first_viewport_path = (
                            output_dir
                            / f"{viewport_name}-{scenario_name}-first-load.png"
                        )
                        page.screenshot(path=str(first_viewport_path), full_page=False)
                        result["first_viewport_screenshot"] = str(first_viewport_path)
                        result["horizontal_overflow"] = bool(
                            page.evaluate(
                                "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                            )
                        )
                        result["bluf_visible"] = _is_in_first_viewport(page, ".cockpit-bluf")
                        result["phase_visible"] = page.locator(".cockpit-phase:not([hidden])").first.is_visible()
                        result["candidate_visible"] = page.locator(".cockpit-candidate-row, .empty-state").count() > 0
                        page_preflight = _preflight(target_url)
                        result["page_preflight_summary"] = _preflight_summary(page_preflight)
                        result["semantic_errors"] = _first_screen_semantic_errors(
                            page,
                            page_preflight,
                        )
                        result["readability_errors"] = _first_screen_readability_errors(page)
                        result["inner_overflow_errors"] = _inner_horizontal_overflow_errors(page)
                        result["submit_gate_safe"] = _submit_gate_is_safe(page)
                        result["focus_errors"] = _exercise_focus(page, args.focus)
                        result["panel_screenshots"] = _screenshot_panels(
                            page,
                            output_dir,
                            f"{viewport_name}-{scenario_name}",
                        )
                        result["unreadable_controls"] = page.evaluate(
                            """
                            () => Array.from(document.querySelectorAll('button, a.button, .cockpit-dashboard-nav a, .status-pill'))
                              .filter((el) => (
                                el.scrollWidth > el.clientWidth + 1 ||
                                el.scrollHeight > el.clientHeight + 1
                              ))
                              .map((el) => (el.textContent || '').trim().replace(/\\s+/g, ' '))
                              .filter(Boolean)
                              .slice(0, 10)
                            """
                        )
                        result["small_touch_targets"] = _small_touch_targets(page)
                        screenshot_path = output_dir / f"{viewport_name}-{scenario_name}-{args.focus}.png"
                        page.screenshot(path=str(screenshot_path), full_page=False)
                        result["screenshot"] = str(screenshot_path)
                    except PlaywrightError as exc:
                        result["error"] = f"{exc.__class__.__name__}: {str(exc).splitlines()[0]}"
                    finally:
                        page.close()
                    results.append(result)
        finally:
            browser.close()

    report_path = output_dir / "cockpit-ux-qa.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for result in results:
        print(result)
    for result in contract_results:
        print(result)
    failures = [result for result in results if _failed(result)]
    contract_failures = [result for result in contract_results if result.get("errors")]
    print(f"preflight={preflight_path}")
    print(f"semantic_contract={contract_path}")
    print(f"report={report_path}")
    print(f"failure_count={len(failures) + len(contract_failures)}")
    return 1 if failures or contract_failures else 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser QA for the V3 cockpit UX.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--focus", default="shell")
    parser.add_argument(
        "--output",
        default="research/results/ux-redesign-v3-qa/latest",
    )
    parser.add_argument(
        "--allow-paper-submit",
        action="store_true",
        help="Permit submit-path checks only when preflight proves readiness.",
    )
    return parser.parse_args(argv)


def _scenario_names(raw: str) -> list[str]:
    if raw == "all":
        return list(SCENARIOS)
    if raw not in SCENARIOS:
        return ["normal"]
    return [raw]


def _preflight(url: str) -> dict[str, object]:
    return {endpoint: _json_get(_endpoint_url(url, endpoint)) for endpoint in PREFLIGHT_ENDPOINTS}


def _scenario_url(url: str, scenario: str) -> str:
    if not scenario or scenario == "normal":
        return url
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["scenario"] = scenario
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def _endpoint_url(url: str, endpoint: str) -> str:
    parsed = urlsplit(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    endpoint_url = urljoin(root, endpoint)
    if endpoint == "/api/cockpit" and parsed.query:
        endpoint_parsed = urlsplit(endpoint_url)
        return urlunsplit(
            (
                endpoint_parsed.scheme,
                endpoint_parsed.netloc,
                endpoint_parsed.path,
                parsed.query,
                endpoint_parsed.fragment,
            )
        )
    return endpoint_url


def _preflight_summary(preflight: Mapping[str, object]) -> dict[str, object]:
    cockpit = _mapping(preflight.get("/api/cockpit"))
    scenario = _mapping(cockpit.get("scenario"))
    data_state = _mapping(cockpit.get("data_state"))
    return {
        "scenario_state": scenario.get("state"),
        "scenario_headline": scenario.get("headline"),
        "data_state_headline": data_state.get("headline"),
        "top_gap_count": len(_mapping_list(data_state.get("top_gaps"))),
    }


def _json_get(url: str) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/json"})
    last_error = ""
    for attempt in range(1, 4):
        try:
            with urlopen(request, timeout=PREFLIGHT_REQUEST_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    return {"available": False, "status_code": response.status}
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt < 3:
                time.sleep(0.5 * attempt)
                continue
            return {"available": False, "error": last_error, "attempts": attempt}
        if isinstance(payload, dict):
            payload.setdefault("available", True)
            payload["attempts"] = attempt
            return payload
        return {"available": True, "payload": payload, "attempts": attempt}
    return {"available": False, "error": last_error or "request not attempted", "attempts": 3}


def _validate_paper_submit_preflight(
    preflight: dict[str, object],
    *,
    allow_paper_submit: bool,
) -> None:
    if not allow_paper_submit:
        return
    readiness = _mapping(preflight.get("/status/full-live-readiness"))
    execution = _mapping(preflight.get("/status/execution-preview"))
    if readiness.get("ready") is not True or readiness.get("tradable_ready") is not True:
        raise RuntimeError("paper submit QA requires fresh readiness evidence")
    orderable = _int(execution.get("orderable_count"))
    submit_ready = _int(execution.get("submit_ready_count"))
    if max(orderable, submit_ready) <= 0:
        raise RuntimeError("paper submit QA requires at least one orderable execution preview")


def _semantic_contract_case_results() -> list[dict[str, object]]:
    """Render required cockpit semantic states through the real route/template."""

    import os

    from fastapi.testclient import TestClient

    import agency.dashboard as dashboard_module
    from agency.app import create_app

    current: dict[str, object] = {}
    original = dashboard_module.cached_cockpit_context_with_timeout
    original_scheduler_enabled = os.environ.get("AGENCY_SCHEDULER_ENABLED")

    async def fake_cockpit_context_with_timeout(**_kwargs: object) -> dict[str, object]:
        return deepcopy(current["context"])  # type: ignore[return-value]

    dashboard_module.cached_cockpit_context_with_timeout = fake_cockpit_context_with_timeout
    os.environ["AGENCY_SCHEDULER_ENABLED"] = "false"
    try:
        with TestClient(create_app()) as client:
            results: list[dict[str, object]] = []
            for case in _semantic_contract_cases():
                current["context"] = case["context"]
                response = client.get("/cockpit")
                api_response = client.get("/api/cockpit")
                api_payload = api_response.json() if api_response.status_code == 200 else {}
                errors = []
                if response.status_code != 200:
                    errors.append(f"/cockpit returned HTTP {response.status_code}")
                if api_response.status_code != 200:
                    errors.append(f"/api/cockpit returned HTTP {api_response.status_code}")
                if response.status_code == 200 and api_response.status_code == 200:
                    errors.extend(
                        _semantic_contract_case_errors(
                            case,
                            api_payload,
                            response.text,
                        )
                    )
                results.append(
                    {
                        "case": case["name"],
                        "expected_state": case["expected_state"],
                        "api_state": _mapping(_mapping(api_payload).get("scenario")).get("state"),
                        "errors": errors,
                    }
                )
            return results
    finally:
        dashboard_module.cached_cockpit_context_with_timeout = original
        if original_scheduler_enabled is None:
            os.environ.pop("AGENCY_SCHEDULER_ENABLED", None)
        else:
            os.environ["AGENCY_SCHEDULER_ENABLED"] = original_scheduler_enabled


def _semantic_contract_cases() -> list[dict[str, object]]:
    return [
        _semantic_case(
            name="review_ready_paper_gated_noncritical_engine_unavailable",
            expected_state="review",
            candidates=[_semantic_candidate("AAPL", reviewable=True)],
            data_state=_semantic_data_state(
                review_ready=True,
                paper_ready=False,
                paper_label="Paper execution gated",
                paper_detail=(
                    "Abnormal Volume needs refresh before paper execution. "
                    "Research review remains usable for covered tickers."
                ),
            ),
            engines=[
                {
                    "name": "Optional email evidence",
                    "state": "down",
                    "detail": "Seeking Alpha login is required; market-data review remains usable.",
                    "age": "checked 2026-06-02 10:00 UTC",
                }
            ],
            required_texts=[
                "1 candidates are ready for research review.",
                "Review ready",
                "Paper execution gated",
                "Research review remains usable",
                "Start reviewing 1 candidate",
            ],
            forbidden_texts=["Selection is paused", "Cockpit status is still loading"],
        ),
        _semantic_case(
            name="review_not_ready_live_trade_slices_need_refresh",
            expected_state="status-delayed",
            data_state=_semantic_data_state(
                review_ready=False,
                paper_ready=False,
                review_label="Review not ready",
                paper_label="Paper execution not ready",
                gaps=[
                    _semantic_gap(
                        lane="Live trade slices",
                        status_label="Needs refresh",
                        detail=(
                            "Live trade slices are outside the review window. "
                            "What remains usable: daily bars, fundamentals, and portfolio context."
                        ),
                        action_label="Refresh live trade slices",
                        action_url="/scheduler/lane/massive_live_trade_slices/refresh",
                    )
                ],
            ),
            required_texts=[
                "Live trade slices",
                "Needs refresh",
                "Refresh live trade slices",
                "What remains usable",
                "confirm proof timestamp changed",
                "2026-06-02 10:00 UTC",
            ],
        ),
        _semantic_case(
            name="missing_source_proof",
            expected_state="outage",
            data_state=_semantic_data_state(
                review_ready=False,
                paper_ready=False,
                review_label="Review not ready",
                paper_label="Paper execution not ready",
                proof_label="not checked",
                gaps=[
                    _semantic_gap(
                        lane="Source proof",
                        status_label="Unavailable",
                        detail=(
                            "The cockpit has no current source-proof rows for this request. "
                            "What remains usable: nothing should be trusted for approval until proof appears."
                        ),
                        action_label="Open Diagnostics for Source proof",
                        action_url="/command",
                        method="get",
                    )
                ],
            ),
            required_texts=[
                "Source proof",
                "Unavailable",
                "Open Diagnostics for Source proof",
                "not checked",
                "nothing should be trusted",
                "confirm proof timestamp changed",
            ],
        ),
        _semantic_case(
            name="email_login_required_market_data_review_usable",
            expected_state="review",
            candidates=[_semantic_candidate("MSFT", reviewable=True)],
            data_state=_semantic_data_state(
                review_ready=True,
                paper_ready=False,
                paper_label="Paper execution gated",
                paper_detail="Paper execution waits for current broker and order-detail checks.",
            ),
            data_health={
                "email_login_alert": {
                    "title": "Seeking Alpha login required",
                    "detail": (
                        "Email evidence needs login, but market-data review remains usable for this cycle."
                    ),
                    "label": "Open Seeking Alpha login refresh",
                    "action": "/scheduler/subscription-emails/login-refresh",
                }
            },
            required_texts=[
                "1 candidates are ready for research review.",
                "Review ready",
                "Seeking Alpha login required",
                "market-data review remains usable",
                "Open Seeking Alpha login refresh",
            ],
            forbidden_texts=["Selection is paused", "Cockpit status is still loading"],
        ),
        _semantic_case(
            name="paper_execution_ready_broker_env_available",
            expected_state="normal",
            candidates=[_semantic_candidate("NVDA", actionable=True)],
            data_state=_semantic_data_state(
                review_ready=True,
                paper_ready=True,
                paper_label="Ready for paper execution",
                paper_detail=(
                    "Broker paper API connected; API keys loaded; paper-only submit gate remains armed by acknowledgement."
                ),
            ),
            required_texts=[
                "1 trades ready. Approve what you want to ship today.",
                "Review ready",
                "Ready for paper execution",
                "Broker paper API connected",
                "API keys loaded",
                "Review 1 ready trade",
            ],
            forbidden_texts=["Selection is paused", "No paper trade is ready right now"],
        ),
    ]


def _semantic_case(
    *,
    name: str,
    expected_state: str,
    data_state: dict[str, object],
    candidates: list[dict[str, object]] | None = None,
    engines: list[dict[str, object]] | None = None,
    data_health: dict[str, object] | None = None,
    required_texts: list[str] | None = None,
    forbidden_texts: list[str] | None = None,
) -> dict[str, object]:
    context = _semantic_context(
        data_state=data_state,
        candidates=candidates or [],
        engines=engines or [],
        data_health=data_health or {},
    )
    return {
        "name": name,
        "context": context,
        "expected_state": expected_state,
        "required_texts": required_texts or [],
        "forbidden_texts": forbidden_texts or [],
    }


def _semantic_context(
    *,
    data_state: dict[str, object],
    candidates: list[dict[str, object]],
    engines: list[dict[str, object]],
    data_health: dict[str, object],
) -> dict[str, object]:
    from agency.views.cockpit import (
        _phase_states,
        _scenario_display_titles,
        _scenario_from_context,
        cockpit_status_delayed_context,
    )

    context = cockpit_status_delayed_context(timeout_seconds=1.0)
    context.update(
        {
            "status_delayed": False,
            "cycle": {
                "id": "semantic-contract-cycle",
                "mode": "PAPER",
                "as_of": "2026-06-02",
                "next_in": "manual semantic QA",
                "submit_enabled": False,
            },
            "monitor": {
                "live": True,
                "label": "Monitor current",
                "last_update": "2026-06-02 10:00 UTC",
            },
            "cockpit_context_freshness": {
                "status_label": "Cockpit data loaded",
                "status_class": "pass",
                "age_seconds": 0,
                "age_label": "just now",
                "source": "semantic contract QA",
                "detail": "Semantic contract QA renders controlled current-proof states.",
            },
            "data_state": data_state,
            "data_health": data_health,
            "engines": engines,
            "candidates": candidates,
            "funnel": {
                "final": len(candidates),
                "actionable": sum(1 for row in candidates if row.get("actionable") is True),
                "reviewable": sum(
                    1
                    for row in candidates
                    if row.get("reviewable") is True or row.get("order_reviewable") is True
                ),
            },
            "clearance": {
                "orderable_count": sum(1 for row in candidates if row.get("actionable") is True),
                "ready_count": sum(1 for row in candidates if row.get("actionable") is True),
                "manifest": [],
                "orders": [],
                "exits": [],
                "submit_phrase": "submit paper orders",
            },
            "qa_scenarios_enabled": False,
            "qa_scenarios": [],
        }
    )
    context["scenario"] = _scenario_display_titles(_scenario_from_context(context, {}))
    context["phase_states"] = _phase_states(context)
    return context


def _semantic_candidate(
    ticker: str,
    *,
    reviewable: bool = False,
    actionable: bool = False,
) -> dict[str, object]:
    ticker = ticker.upper()
    return {
        "ticker": ticker,
        "rank": 1,
        "name": f"{ticker} Inc.",
        "sector": "Technology",
        "status": "ready",
        "status_label": "Ready for paper execution" if actionable else "Ready for research review",
        "reviewable": reviewable,
        "actionable": actionable,
        "order_reviewable": False,
        "evidence_tiers": ["confirmed"],
        "evidence_line": f"{ticker} has current semantic QA evidence attached.",
        "evidence": [
            {
                "tier": "confirmed",
                "source": "Semantic contract QA",
                "text": f"{ticker} current proof, signal direction, and risk note are visible.",
            }
        ],
        "risk_status_label": "WARN" if not actionable else "ALLOW",
        "risk_line": "Paper gate reason is written in plain English.",
        "llm_label": "LLM not required for semantic QA",
        "llm_rationale": "Semantic QA fixture.",
        "final_conviction": 0.72,
        "score_display": "0.72",
        "det_conviction": 0.72,
        "llm_conviction": 0.0,
        "approve_review_action": f"/candidates/{ticker}/review/approve",
        "defer_review_action": f"/candidates/{ticker}/review/defer",
        "reject_review_action": f"/candidates/{ticker}/review/reject",
        "execution_focus_url": f"/execution-preview?ticker={ticker}#focused-preview-{ticker}",
        "audit_url": f"/candidates/{ticker}",
    }


def _semantic_data_state(
    *,
    review_ready: bool,
    paper_ready: bool,
    review_label: str | None = None,
    paper_label: str | None = None,
    review_detail: str | None = None,
    paper_detail: str | None = None,
    proof_label: str = "2026-06-02 10:00 UTC",
    gaps: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    top_gaps = gaps or []
    return {
        "review": {
            "ready": review_ready,
            "label": review_label or ("Review ready" if review_ready else "Review not ready"),
            "status_class": "pass" if review_ready else "warn",
            "detail": review_detail
            or (
                "The loaded evidence is usable for research review."
                if review_ready
                else "Research review needs the listed data or agent gaps resolved first."
            ),
        },
        "paper": {
            "ready": paper_ready,
            "label": paper_label
            or ("Ready for paper execution" if paper_ready else "Paper execution gated"),
            "status_class": "pass" if paper_ready else "warn",
            "detail": paper_detail
            or (
                "Paper execution can proceed after broker and order approval checks."
                if paper_ready
                else "Resolve or acknowledge the listed readiness items before paper submit."
            ),
        },
        "headline": (
            "Review ready; paper execution proof is current."
            if review_ready and paper_ready
            else "Review is usable; paper execution still needs attention."
            if review_ready
            else "Review cannot continue until the listed proof is refreshed."
        ),
        "overall_percent": 100 if review_ready else 72,
        "critical_lane_percent": 100 if review_ready else 68,
        "active_universe_label": "168 active tickers",
        "proof_label": proof_label,
        "as_of_label": "2026-06-02",
        "top_gaps": top_gaps,
        "lane_rows": [
            {
                "lane_id": "semantic_contract",
                "name": "Semantic contract proof",
                "state": "ready_for_review" if review_ready else "needs_refresh",
                "state_label": "Ready for review" if review_ready else "Needs refresh",
                "status_label": "Ready for review" if review_ready else "Needs refresh",
                "status_class": "pass" if review_ready else "warn",
                "tooltip": "Semantic contract QA row with complete action metadata.",
                "lane_kind_label": "QA",
                "requirement_label": "current proof",
                "required_label": "Required now",
                "blocks_paper_label": "Yes" if not paper_ready else "No",
                "progress_label": "semantic case",
                "eta_label": "now",
                "progress_percent": 100 if review_ready else 72,
                "latest_as_of_label": proof_label,
                "checked_at_label": proof_label,
                "gap_detail": (
                    "No required gap for this semantic case."
                    if review_ready
                    else "Semantic contract gap requires operator action."
                ),
                "recommended_action": (
                    "Continue normal review."
                    if review_ready
                    else "Refresh the source, then confirm proof timestamp changed."
                ),
                "refresh_action": {
                    "label": "Refresh semantic proof",
                    "url": "" if review_ready else "/command",
                    "detail": "Refresh the semantic proof source and verify the proof timestamp changed.",
                },
                "ready_for_review": review_ready,
                "ready_for_paper": paper_ready,
            }
        ],
    }


def _semantic_gap(
    *,
    lane: str,
    status_label: str,
    detail: str,
    action_label: str,
    action_url: str,
    method: str = "post",
) -> dict[str, object]:
    return {
        "lane": lane,
        "status_label": status_label,
        "status_class": "warn",
        "progress_label": "checked 2026-06-02 10:00 UTC",
        "detail": detail,
        "recommended_action": (
            f"{action_label}, then reload the cockpit and confirm proof timestamp changed."
        ),
        "blocks_execution": True,
        "refresh_action": {
            "label": action_label,
            "url": action_url,
            "method": method,
            "detail": f"{action_label}; then confirm proof timestamp changed.",
        },
    }


def _semantic_contract_case_errors(
    case: Mapping[str, object],
    api_payload: Mapping[str, object],
    rendered_html: str,
) -> list[str]:
    errors: list[str] = []
    html_text = _normalized_html_text(rendered_html)
    scenario = _mapping(api_payload.get("scenario"))
    data_state = _mapping(api_payload.get("data_state"))
    review = _mapping(data_state.get("review"))
    rendered_state = _rendered_scenario_state(rendered_html)
    expected_state = str(case.get("expected_state") or "")
    api_state = str(scenario.get("state") or "")
    headline = str(scenario.get("headline") or "").strip()
    review_label = str(review.get("label") or "").strip()

    if expected_state and api_state != expected_state:
        errors.append(f"API state {api_state!r} did not match expected {expected_state!r}.")
    if expected_state and rendered_state != expected_state:
        errors.append(
            f"Rendered state {rendered_state!r} did not match expected {expected_state!r}."
        )
    if headline and not _text_present(html_text, headline):
        errors.append(f"Rendered BLUF is missing API headline {headline!r}.")
    if review_label and not _text_present(html_text, review_label):
        errors.append(f"Rendered Session Readiness is missing review label {review_label!r}.")
    if review.get("ready") is True and (
        rendered_state in {"outage", "status-delayed"} or "selection paused" in html_text.lower()
    ):
        errors.append("Review-ready case rendered as paused/delayed.")
    for text in case.get("required_texts", []):
        if isinstance(text, str) and not _text_present(html_text, text):
            errors.append(f"Required first-screen text is missing: {text!r}.")
    for text in case.get("forbidden_texts", []):
        if isinstance(text, str) and _text_present(html_text, text):
            errors.append(f"Forbidden first-screen text is present: {text!r}.")
    for gap in _mapping_list(data_state.get("top_gaps")):
        for key in ("lane", "status_label", "detail", "recommended_action"):
            value = str(gap.get(key) or "").strip()
            if value and not _text_present(html_text, value[:72]):
                errors.append(f"Rendered blocker proof is missing {key} {value[:72]!r}.")
        action = _mapping(gap.get("refresh_action"))
        label = str(action.get("label") or "").strip()
        if label and not _text_present(html_text, label):
            errors.append(f"Rendered blocker proof is missing action {label!r}.")
    return errors


def _normalized_html_text(rendered_html: str) -> str:
    return " ".join(html_unescape(rendered_html).split())


def _text_present(haystack: str, needle: str) -> bool:
    return " ".join(needle.split()).casefold() in haystack.casefold()


def _rendered_scenario_state(rendered_html: str) -> str:
    marker = 'data-cockpit-scenario="'
    if marker not in rendered_html:
        return ""
    return rendered_html.split(marker, 1)[1].split('"', 1)[0]


def _console_error_collector(console_errors: list[str]):
    def collect(message: Any) -> None:
        if message.type == "error":
            console_errors.append(str(message.text))

    return collect


def _page_error_collector(page_errors: list[str]):
    def collect(exc: BaseException) -> None:
        page_errors.append(str(exc))

    return collect


def _external_request_collector(external_requests: list[str], page_url: str):
    allowed = urlsplit(page_url).netloc

    def collect(request: Any) -> None:
        parsed = urlsplit(request.url)
        if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.netloc != allowed:
            external_requests.append(request.url)

    return collect


def _is_in_first_viewport(page: Any, selector: str) -> bool:
    return bool(
        page.locator(selector).first.evaluate(
            """
            (el) => {
              const rect = el.getBoundingClientRect();
              return rect.top >= 0 && rect.top < window.innerHeight && rect.bottom > 0;
            }
            """
        )
    )


def _viewport_width(page: Any) -> int:
    return int(page.evaluate("() => window.innerWidth") or 0)


def _submit_gate_is_safe(page: Any) -> bool:
    clearance = page.locator('[data-cockpit-phase-target="clearance"]').first
    if clearance.count() > 0:
        clearance.click()
    scenario_state = (
        page.locator("[data-cockpit-cycle]").first.get_attribute("data-cockpit-scenario")
        or "normal"
    )
    safety_scenario = scenario_state in {"outage", "status-delayed", "no-actionable", "submitted"}
    button = page.locator("[data-cockpit-submit-button]").first
    if button.count() == 0:
        return True
    initially_disabled = button.is_disabled()
    ack = page.locator("[data-cockpit-submit-ack]").first
    phrase = page.locator("[data-cockpit-submit-text]").first
    if safety_scenario and (
        ack.count() == 0
        or phrase.count() == 0
        or not ack.is_visible()
        or not phrase.is_visible()
    ):
        return initially_disabled
    if ack.count() == 0 or phrase.count() == 0:
        return False
    manifest_ready = _paper_manifest_has_order_intent(page)
    ack.check()
    phrase.fill("wrong phrase")
    wrong_phrase_disabled = button.is_disabled()
    phrase.fill("submit paper orders")
    armed_enabled = not button.is_disabled()
    phrase.fill("")
    ack.uncheck()
    if safety_scenario:
        return initially_disabled and wrong_phrase_disabled and not armed_enabled
    if not manifest_ready:
        return initially_disabled and wrong_phrase_disabled and not armed_enabled
    return initially_disabled and wrong_phrase_disabled and armed_enabled


def _paper_manifest_has_order_intent(page: Any) -> bool:
    return bool(
        page.evaluate(
            """
            () => Array.from(document.querySelectorAll('[data-cockpit-manifest-row]'))
              .some((row) => {
                if (row.classList.contains('cockpit-manifest-exit')) return false;
                const required = ['cycle_id', 'ticker', 'as_of', 'order_intent_hash'];
                return required.every((name) => {
                  const input = row.querySelector(`input[name="${name}"]`);
                  return input && String(input.value || '').trim().length > 0;
                });
              })
            """
        )
    )


def _small_touch_targets(page: Any) -> list[str]:
    return page.evaluate(
        """
        () => Array.from(document.querySelectorAll(
          '.cockpit-shell button, .cockpit-shell a.button, .cockpit-dashboard-nav a, .cockpit-shell [role="button"], .cockpit-shell summary'
        ))
          .filter((el) => {
            if (el.closest('[hidden]') || el.hasAttribute('hidden')) {
              return false;
            }
            const style = window.getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') {
              return false;
            }
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
          })
          .map((el) => {
            const rect = el.getBoundingClientRect();
            const label = (el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.tagName)
              .trim()
              .replace(/\\s+/g, ' ');
            return `${label || el.tagName} ${Math.round(rect.width)}x${Math.round(rect.height)}`;
          })
          .slice(0, 20)
        """
    )


def _failed(result: dict[str, object]) -> bool:
    return (
        result.get("http_ok") is not True
        or bool(result.get("console_errors"))
        or bool(result.get("page_errors"))
        or bool(result.get("external_requests"))
        or result.get("horizontal_overflow") is True
        or result.get("bluf_visible") is not True
        or result.get("phase_visible") is not True
        or result.get("candidate_visible") is not True
        or result.get("submit_gate_safe") is not True
        or bool(result.get("focus_errors"))
        or bool(result.get("semantic_errors"))
        or bool(result.get("readability_errors"))
        or bool(result.get("inner_overflow_errors"))
        or bool(result.get("unreadable_controls"))
        or bool(result.get("small_touch_targets"))
        or bool(result.get("error"))
    )


def _first_screen_semantic_errors(
    page: Any,
    preflight: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    cockpit_api = _mapping(preflight.get("/api/cockpit"))
    if cockpit_api.get("available") is False:
        errors.append(f"/api/cockpit unavailable for rendered-page comparison: {cockpit_api}")
        return errors
    scenario = _mapping(cockpit_api.get("scenario"))
    data_state = _mapping(cockpit_api.get("data_state"))
    if not scenario:
        errors.append("Rendered-page comparison has no /api/cockpit scenario payload.")
    if not data_state:
        errors.append("Rendered-page comparison has no /api/cockpit data_state payload.")
    review = _mapping(data_state.get("review"))
    paper = _mapping(data_state.get("paper"))
    top_gaps = _mapping_list(data_state.get("top_gaps"))
    errors.extend(_cross_endpoint_truth_errors(preflight))

    bluf = _locator_text(page, ".cockpit-bluf")
    expected_headline = str(scenario.get("headline") or "").strip()
    if expected_headline and _normalize_space(expected_headline) != _normalize_space(bluf):
        errors.append(
            f"BLUF mismatch: API headline {expected_headline!r} but rendered {bluf!r}"
        )
    rendered_visible_text = _locator_text(page, ".cockpit-shell")
    if "selection is paused" in rendered_visible_text.casefold():
        errors.append("Cockpit must explain locked controls without saying selection is paused.")

    primary_nav = _mapping(scenario.get("primary_nav_action"))
    primary_nav_label = str(primary_nav.get("label") or "").strip()
    if primary_nav_label:
        rendered_topline = _locator_text(page, ".cockpit-topline")
        if primary_nav_label.casefold() not in rendered_topline.casefold():
            errors.append(
                f"Primary workflow action {primary_nav_label!r} is missing from the first-screen briefing."
            )

    primary_action = _mapping(scenario.get("primary_action"))
    primary_action_label = str(primary_action.get("label") or "").strip()
    if primary_action_label:
        rendered_topline = _locator_text(page, ".cockpit-topline")
        if primary_action_label.casefold() not in rendered_topline.casefold():
            errors.append(
                f"Primary data action {primary_action_label!r} is missing from the first-screen briefing."
            )

    dashboard_nav = _locator_text(page, ".cockpit-dashboard-nav")
    for expected in ("Signals", "Fundamentals", "Portfolio", "Market", "System Status"):
        if expected.casefold() not in dashboard_nav.casefold():
            errors.append(f"Cockpit dashboard navigation is missing {expected!r}.")
    first_nav = _locator_text(page, ".cockpit-first-nav")
    for expected in ("Fix Data", "Signals", "Fundamentals", "Portfolio", "SA Login"):
        if expected.casefold() not in first_nav.casefold():
            errors.append(f"First-screen dashboard navigation is missing {expected!r}.")
    first_viewport_text = _first_viewport_text(page)
    for forbidden in ("legacy", "diagnostic"):
        if forbidden in first_viewport_text.casefold():
            errors.append(
                f"First viewport still exposes internal '{forbidden}' wording to the operator."
            )

    data_state_text = _locator_text(page, ".cockpit-data-state-strip")
    for label_name, row in (("review", review), ("paper", paper)):
        label = str(row.get("label") or "").strip()
        if label and label not in data_state_text:
            errors.append(f"Rendered data-state strip is missing {label_name} label {label!r}.")

    rendered_state = str(
        page.locator(".cockpit-shell").first.get_attribute("data-cockpit-scenario") or ""
    )
    api_state = str(scenario.get("state") or "")
    if api_state and rendered_state and rendered_state != api_state:
        errors.append(
            f"Scenario state mismatch: API {api_state!r} but shell has {rendered_state!r}."
        )
    if review.get("ready") is True and rendered_state in {"outage", "status-delayed"}:
        errors.append(f"Review-ready API state rendered as a {rendered_state} cockpit.")
    if review.get("ready") is True and "selection paused" in data_state_text.casefold():
        errors.append("Review-ready cockpit must not say selection is paused.")

    viewport_width = _viewport_width(page)
    if not _is_in_first_viewport(page, ".cockpit-proof-strip"):
        errors.append("First viewport is missing the proof strip.")
    if not _is_in_first_viewport(page, ".cockpit-operator-path"):
        errors.append("First viewport is missing the operator next-step path.")
    if viewport_width >= 760 and not _is_in_first_viewport(page, ".cockpit-data-state-strip"):
        errors.append("First viewport is missing the data-state strip.")
    if viewport_width < 760:
        compact_state = _locator_text(page, ".cockpit-operator-path")
        for required_mobile in ("review", "paper", "fix"):
            if required_mobile not in compact_state.casefold():
                errors.append(
                    f"Mobile first viewport is missing compact readiness text {required_mobile!r}."
                )
    if not _is_in_first_viewport(page, ".cockpit-first-nav"):
        errors.append("First viewport is missing primary dashboard navigation.")
    if (
        rendered_state not in {"outage", "status-delayed"}
        and not _is_in_first_viewport(page, ".cockpit-phase-rail")
    ):
        errors.append("First viewport is missing the workflow phase rail.")
    if (
        rendered_state not in {"outage", "status-delayed"}
        and viewport_width >= 760
        and not _is_in_first_viewport(page, ".cockpit-instrument-cluster")
    ):
        errors.append("First viewport is missing the cockpit instruments.")
    for required in ("review", "proof"):
        if required not in first_viewport_text.casefold():
            errors.append(f"First viewport is missing operator proof text {required!r}.")

    if top_gaps:
        rendered_gap_count = page.locator(".cockpit-data-state-gap").count()
        if rendered_gap_count == 0:
            errors.append("API reports top data gaps, but no data-state gap cards are rendered.")
        for index, gap in enumerate(top_gaps[:3]):
            lane = str(gap.get("lane") or "").strip()
            status_label = str(gap.get("status_label") or "").strip()
            recommended = str(gap.get("recommended_action") or "").strip()
            action = _mapping(gap.get("refresh_action"))
            action_label = str(action.get("label") or "").strip()
            compare_text = first_viewport_text if index == 0 else data_state_text
            if lane and lane not in data_state_text:
                errors.append(f"Top data gap {index + 1} lane {lane!r} is not visible.")
            if status_label and status_label not in data_state_text:
                errors.append(f"Top data gap {index + 1} status {status_label!r} is not visible.")
            if lane and f"{lane} proof is not ready" not in data_state_text:
                errors.append(f"Top data gap {index + 1} plain-English proof state is not visible.")
            if recommended and recommended[:32] not in compare_text:
                errors.append(f"Top data gap {index + 1} recommendation is not visible.")
            if action_label and action_label not in compare_text:
                errors.append(
                    f"Top data-gap action {action_label!r} is not visible in the operator workflow."
                )
            if not action_label and "Review data sources" not in data_state_text:
                errors.append(f"Top data gap {index + 1} has no visible action button.")

    data_health = _mapping(cockpit_api.get("data_health"))
    if _mapping(data_health.get("email_login_alert")) and review.get("ready") is True:
        email_text = _locator_text(page, "#email-agent, #email-agent-controls")
        if "seeking alpha" not in email_text.casefold() and "email" not in email_text.casefold():
            errors.append("Email-login alert is required but not visible on the first screen.")
        if rendered_state in {"outage", "status-delayed"}:
            errors.append(
                "Email-login requirement must not render market-data review as an outage or delayed cockpit."
            )
    errors.extend(_candidate_dom_api_errors(page, cockpit_api))
    return errors


def _cross_endpoint_truth_errors(preflight: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    cockpit_api = _mapping(preflight.get("/api/cockpit"))
    data_load = _mapping(preflight.get("/status/data-load"))
    execution = _mapping(preflight.get("/status/execution-preview"))
    if not cockpit_api or data_load.get("available") is False:
        return errors

    data_state = _mapping(cockpit_api.get("data_state"))
    review = _mapping(data_state.get("review"))
    paper = _mapping(data_state.get("paper"))
    data_review_ready = data_load.get("review_operational_ready")
    if isinstance(data_review_ready, bool) and review.get("ready") is not data_review_ready:
        errors.append(
            "Cross-endpoint mismatch: /api/cockpit review.ready "
            f"{review.get('ready')!r} but /status/data-load review_operational_ready "
            f"{data_review_ready!r}."
        )
    data_tradable_ready = data_load.get("tradable_ready")
    if isinstance(data_tradable_ready, bool) and paper.get("ready") is not data_tradable_ready:
        errors.append(
            "Cross-endpoint mismatch: /api/cockpit paper.ready "
            f"{paper.get('ready')!r} but /status/data-load tradable_ready "
            f"{data_tradable_ready!r}."
        )

    if execution.get("available") is False:
        return errors
    clearance = _mapping(cockpit_api.get("clearance"))
    cockpit_orderable = _int(clearance.get("orderable_count"))
    cockpit_ready = _int(clearance.get("ready_count"))
    execution_orderable = _int(execution.get("orderable_count"))
    execution_submit_ready = _int(execution.get("submit_ready_count"))
    if cockpit_orderable != execution_orderable:
        errors.append(
            "Cross-endpoint mismatch: /api/cockpit clearance.orderable_count "
            f"{cockpit_orderable} but /status/execution-preview orderable_count "
            f"{execution_orderable}."
        )
    if cockpit_ready != execution_submit_ready:
        errors.append(
            "Cross-endpoint mismatch: /api/cockpit clearance.ready_count "
            f"{cockpit_ready} but /status/execution-preview submit_ready_count "
            f"{execution_submit_ready}."
        )
    return errors


def _first_viewport_text(page: Any) -> str:
    return str(
        page.evaluate(
            """
            () => Array.from(document.body.querySelectorAll('*'))
              .filter((el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                  rect.top < window.innerHeight && rect.bottom > 0 &&
                  style.visibility !== 'hidden' && style.display !== 'none';
              })
              .map((el) => (el.textContent || '').trim().replace(/\\s+/g, ' '))
              .filter(Boolean)
              .join(' ')
            """
        )
    )


def _candidate_dom_api_errors(
    page: Any,
    cockpit_api: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    candidates = _mapping_list(cockpit_api.get("candidates"))
    rendered = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('[data-cockpit-candidate]'))
          .slice(0, 5)
          .map((row) => ({
            ticker: row.getAttribute('data-cockpit-ticker') || '',
            text: (row.textContent || '').trim().replace(/\\s+/g, ' ')
          }))
        """
    )
    rendered_rows = rendered if isinstance(rendered, list) else []
    if candidates and not rendered_rows:
        errors.append("API reports candidates, but no candidate rows are rendered.")
        return errors
    for index, candidate in enumerate(candidates[: min(5, len(rendered_rows))]):
        rendered_row = _mapping(rendered_rows[index])
        expected_ticker = str(candidate.get("ticker") or "").upper()
        rendered_ticker = str(rendered_row.get("ticker") or "").upper()
        rendered_text = str(rendered_row.get("text") or "")
        if expected_ticker and rendered_ticker != expected_ticker:
            errors.append(
                f"Candidate row {index + 1} ticker mismatch: API {expected_ticker}, rendered {rendered_ticker}."
            )
        for key, label in (
            ("status_label", "status label"),
            ("evidence_line", "evidence line"),
            ("risk_line", "risk line"),
        ):
            value = str(candidate.get(key) or "").strip()
            if value and value[:48] not in rendered_text:
                errors.append(
                    f"Candidate {expected_ticker or index + 1} rendered row is missing API {label}."
                )
        score = str(candidate.get("score_display") or "").strip()
        if score and score not in rendered_text:
            errors.append(f"Candidate {expected_ticker} rendered row is missing score {score!r}.")
        if candidate.get("actionable") is True or candidate.get("reviewable") is True:
            for key, label in (("cycle_id", "cycle id"), ("as_of_label", "as-of timestamp")):
                value = str(candidate.get(key) or "").strip()
                if value and value not in rendered_text:
                    errors.append(
                        f"Candidate {expected_ticker} rendered row is missing visible {label} proof."
                    )
    return errors


def _first_screen_readability_errors(page: Any) -> list[str]:
    return list(
        page.evaluate(
            """
            () => {
              const errors = [];
              const px = (value) => Number.parseFloat(String(value || '0').replace('px', '')) || 0;
              const visible = (el) => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const text = (el) => (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
              const fontCheck = (selector, label, minPx) => {
                const el = document.querySelector(selector);
                if (!visible(el)) return;
                const size = px(getComputedStyle(el).fontSize);
                if (size < minPx) errors.push(`${label} font ${size.toFixed(1)}px is below ${minPx}px`);
              };
              fontCheck('.cockpit-bluf', 'BLUF', window.innerWidth < 500 ? 22 : 28);
              fontCheck('.cockpit-topline .muted', 'BLUF supporting copy', 15);
              fontCheck('.cockpit-data-state-headline h2', 'Data State headline', 20);
              fontCheck('.cockpit-data-state-gap p', 'Data State gap explanation', 15);

              const headline = document.querySelector('.cockpit-data-state-headline');
              const h2 = document.querySelector('.cockpit-data-state-headline h2');
              if (visible(headline) && visible(h2)) {
                const gap = h2.getBoundingClientRect().top - headline.getBoundingClientRect().top;
                if (gap > 96) errors.push(`Data State headline starts ${Math.round(gap)}px below its panel top`);
              }

              const actionSelectors = [
                '.cockpit-first-nav a',
                '.cockpit-operator-step',
                '.cockpit-top-actions .button',
                '.cockpit-primary-action .button',
                '.cockpit-dashboard-nav a',
                '.cockpit-data-state-gap .button',
                '.cockpit-email-login-alert button',
                '.review-action-form .button',
                '.cockpit-decision-cell button'
              ];
              const seen = new Set();
              actionSelectors.forEach((selector) => {
                document.querySelectorAll(selector).forEach((el) => {
                  if (!visible(el) || seen.has(el)) return;
                  seen.add(el);
                  const rect = el.getBoundingClientRect();
                  if (rect.top > window.innerHeight) return;
                  const style = getComputedStyle(el);
                  const size = px(style.fontSize);
                  if (rect.height < 52) {
                    errors.push(`Action button "${text(el)}" is ${Math.round(rect.height)}px high; expected at least 52px`);
                  }
                  if (size < 15) {
                    errors.push(`Action button "${text(el)}" font ${size.toFixed(1)}px is below 15px`);
                  }
                  const bg = style.backgroundColor;
                  const bgImage = style.backgroundImage || 'none';
                  if ((selector.includes('data-state-gap') || selector.includes('email-login')) && bgImage === 'none' && /rgba?\\(\\s*(0|1|2?\\d),/.test(bg)) {
                    errors.push(`Action button "${text(el)}" background ${bg} is too visually recessive`);
                  }
                });
              });
              return errors;
            }
            """
        )
    )


def _inner_horizontal_overflow_errors(page: Any) -> list[str]:
    return list(
        page.evaluate(
            """
            () => {
              const viewportWidth = document.documentElement.clientWidth;
              const labels = [
                ['app shell', '.app-shell'],
                ['page frame', '.page-frame'],
                ['layout', '.layout'],
                ['cockpit shell', '.cockpit-shell'],
                ['top briefing', '.cockpit-topline'],
                ['primary action', '.cockpit-primary-action'],
                ['readiness strip', '.cockpit-data-state-strip'],
                ['action gaps', '.cockpit-data-state-gaps'],
                ['dashboard nav', '.cockpit-dashboard-nav'],
                ['email agent', '.cockpit-email-agent-control']
              ];
              const errors = [];
              for (const [label, selector] of labels) {
                const el = document.querySelector(selector);
                if (!el) continue;
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) {
                  continue;
                }
                if (el.scrollWidth > el.clientWidth + 2) {
                  errors.push(`${label} has hidden horizontal overflow: scrollWidth ${el.scrollWidth}px > clientWidth ${el.clientWidth}px`);
                }
                if (rect.left < -1 || rect.right > viewportWidth + 1) {
                  errors.push(`${label} extends outside viewport: left ${Math.round(rect.left)}px right ${Math.round(rect.right)}px viewport ${viewportWidth}px`);
                }
              }
              return errors;
            }
            """
        )
    )


def _locator_text(page: Any, selector: str) -> str:
    locator = page.locator(selector).first
    if locator.count() == 0:
        return ""
    return str(locator.inner_text()).strip().replace("\n", " ")


def _normalize_space(value: object) -> str:
    return " ".join(str(value or "").split())


def _exercise_focus(page: Any, focus: str) -> list[str]:
    errors: list[str] = []
    if focus == "candidates":
        candidates_phase = page.locator('[data-cockpit-phase-target="candidates"]').first
        if candidates_phase.count() > 0:
            if not _try_click(candidates_phase):
                errors.append("candidate phase target was not clickable")
                return errors
            candidate_panel = page.locator('[data-cockpit-phase="candidates"]').first
            if candidate_panel.count() == 0:
                errors.append("candidate phase panel is missing")
                return errors
            if not candidate_panel.is_visible():
                errors.append("candidate phase did not open")
                return errors
        row_toggle = page.locator(
            '[data-cockpit-phase="candidates"]:not([hidden]) [data-cockpit-row-toggle]'
        ).first
        if row_toggle.count() > 0:
            if not _try_click(row_toggle):
                errors.append("candidate row expansion control was not clickable")
                return errors
            if not page.locator(
                '[data-cockpit-phase="candidates"]:not([hidden]) .cockpit-row-detail'
            ).first.is_visible():
                errors.append("candidate row expansion did not open")
    elif focus == "portfolio":
        phase_button = page.locator('[data-cockpit-phase-target="portfolio"]')
        if phase_button.count() == 0 or not phase_button.first.is_visible():
            errors.append("portfolio phase target is missing or hidden")
            return errors
        if not _try_click(phase_button.first):
            errors.append("portfolio phase target was not clickable")
            return errors
        portfolio_phase = page.locator('[data-cockpit-phase="portfolio"]')
        if portfolio_phase.count() == 0:
            errors.append("portfolio phase panel is missing")
        elif not portfolio_phase.first.is_visible():
            errors.append("portfolio phase did not open")
    elif focus == "preferences":
        preferences_button = page.locator("[data-cockpit-preferences-open]").first
        if preferences_button.count() == 0:
            errors.append("preferences entry point is missing")
            return errors
        if not _try_click(preferences_button):
            errors.append("preferences entry point was not clickable")
            return errors
        panel = page.locator("[data-cockpit-preferences]").first
        if panel.count() == 0 or not panel.is_visible():
            errors.append("preferences panel did not open")
            return errors
        page.locator('[name="cockpit-color-preset"][value="duotone"]').check()
        page.locator('[name="cockpit-theme"][value="light"]').check()
        page.locator('[name="cockpit-density"][value="calm"]').check()
        page.reload(wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        page.wait_for_selector(".cockpit-data-state-strip", timeout=10_000)
        shell = page.locator("[data-cockpit-cycle]").first
        expected = {
            "data-cockpit-color-preset": "duotone",
            "data-cockpit-theme": "light",
            "data-cockpit-density": "calm",
        }
        for attribute, value in expected.items():
            if shell.get_attribute(attribute) != value:
                errors.append(f"preference {attribute} did not persist after reload")
    elif focus == "panels":
        for panel in PANEL_NAMES:
            trigger = page.locator(f'[data-cockpit-panel-target="{panel}"]').first
            if not _try_click(trigger):
                errors.append(f"{panel} panel trigger was not clickable")
                continue
            panel_locator = page.locator(f"#cockpit-panel-{panel}")
            if not panel_locator.is_visible():
                errors.append(f"{panel} panel did not open")
            _try_click(panel_locator.locator("button[data-cockpit-panel-close]").first)
        candidates_phase = page.locator('[data-cockpit-phase-target="candidates"]').first
        if candidates_phase.count() > 0:
            _try_click(candidates_phase)
        if page.locator("[data-cockpit-row-toggle]").first.count() > 0:
            _try_click(page.locator("[data-cockpit-row-toggle]").first)
        detail_button = page.locator("[data-cockpit-ticker-detail]").first
        if detail_button.count() > 0:
            if not _try_click(detail_button):
                errors.append("ticker detail trigger was not clickable")
                return errors
            if not page.locator("#cockpit-panel-ticker-detail").is_visible():
                errors.append("ticker detail panel did not open")
            _try_click(
                page.locator("#cockpit-panel-ticker-detail button[data-cockpit-panel-close]").first
            )
    return errors


def _screenshot_panels(page: Any, output_dir: Path, viewport_name: str) -> list[str]:
    screenshots: list[str] = []
    for panel in PANEL_NAMES:
        trigger = page.locator(f'[data-cockpit-panel-target="{panel}"]').first
        if trigger.count() == 0:
            continue
        if not _try_click(trigger):
            continue
        panel_locator = page.locator(f"#cockpit-panel-{panel}")
        if panel_locator.is_visible():
            path = output_dir / f"{viewport_name}-panel-{panel}.png"
            panel_locator.screenshot(path=str(path))
            screenshots.append(str(path))
        _try_click(panel_locator.locator("button[data-cockpit-panel-close]").first)
    return screenshots


def _try_click(locator: Any, *, timeout_ms: int = 1_500) -> bool:
    try:
        if locator.count() == 0 or not locator.is_visible():
            return False
        locator.click(timeout=timeout_ms)
    except Exception:  # noqa: BLE001 - QA should record clickability instead of hanging
        return False
    return True


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, dict)]


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
