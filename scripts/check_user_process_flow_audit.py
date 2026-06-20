from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import requests

EXPECTED_V3_BUILD = "ux-v3-cockpit-readability-20260601"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT_DIR = "research/results/user-process-flow-audit/latest"
KEY_ROUTES = (
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
)
FORBIDDEN_UX_TERMS = (
    "stale",
    "monkey",
    "fake",
    "fixture",
    "mock",
    "bootstrap",
    "first-version",
    "lorem",
    "todo",
)
OPERATOR_STATE_FIELDS = (
    "status_label",
    "detail",
    "operator_message",
    "recommended_action",
    "source_proof_label",
    "refresh_action_label",
    "refresh_action_detail",
    "refresh_action_disabled_reason",
)
LANE_STATE_REQUIRED_FIELDS = (
    "lane_id",
    "lane_kind",
    "state",
    "status_label",
    "status_class",
    "operator_message",
    "recommended_action",
    "latest_as_of",
    "checked_at",
    "progress_label",
    "progress_percent",
    "eta_label",
    "source_proof_label",
)
AGENT_ROW_REQUIRED_FIELDS = (
    "lane",
    "label",
    "group",
    "analysis_state",
    "source_dataset",
    "status_label",
    "status_class",
    "detail",
    "coverage_pct",
    "produced_count",
    "source_status",
    "source_freshness",
)
DATASET_ROW_REQUIRED_FIELDS = (
    "dataset",
    "label",
    "status_label",
    "status_class",
    "detail",
    "coverage_pct",
    "max_as_of",
    "source_status",
    "source_freshness",
)
ACTIONABLE_STATE_MARKERS = (
    "wait",
    "run",
    "refresh",
    "check",
    "fix",
    "open",
    "continue",
    "no action required",
)
_FORBIDDEN_PATTERNS = tuple(
    (
        term,
        re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", re.IGNORECASE),
    )
    for term in FORBIDDEN_UX_TERMS
)


@dataclass(frozen=True)
class FetchResult:
    route: str
    status_code: int
    body: str
    elapsed_seconds: float
    error: str = ""


@dataclass(frozen=True)
class PostResult:
    route: str
    status_code: int
    location: str
    body: str
    elapsed_seconds: float
    error: str = ""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()

    execution_payload = json_get(args.base_url, "/status/execution-preview", args.timeout)
    paper_review_payload = json_get(args.base_url, "/status/paper-review", args.timeout)
    data_load_payload = json_get(args.base_url, "/status/data-load", args.timeout)
    data_sources_payload = json_get(args.base_url, "/status/data-sources", args.timeout)
    scheduler_payload = json_get(args.base_url, "/status/scheduler-work-queue", args.timeout)
    execution_rows = status_rows(execution_payload)
    execution_status_result = audit_execution_status_payload(
        execution_payload,
        execution_rows,
    )
    data_load_contract_results = audit_data_load_status_contract(data_load_payload)
    data_source_contract_results = audit_data_sources_contract(data_sources_payload)
    scheduler_contract_results = audit_scheduler_status_contract(scheduler_payload)
    paper_queue_tickers = paper_review_tickers(paper_review_payload)
    tickers = audit_ticker_sample(
        status_tickers(execution_payload),
        paper_queue_tickers,
        max_tickers=args.max_tickers,
    )
    if args.max_tickers > 0:
        execution_rows = _execution_rows_for_sample(execution_rows, tickers)

    key_page_results = audit_key_pages(
        args.base_url,
        args.timeout,
        route_budget_seconds=args.route_budget_seconds,
    )
    command_result = fetch_text(args.base_url, "/command", args.timeout)
    if command_result.status_code == 200:
        command_failures = audit_command_links(
            command_result.body,
            paper_queue_tickers,
        )
    else:
        command_failures = [
            failure(
                "command_html_unavailable",
                "/command",
                f"Could not verify Command execute links: {command_result.error}",
            )
        ]
    status_contract_results = audit_execution_status_contracts(execution_rows, tickers)
    focus_route_tickers = (
        tickers
        if args.all_focus_routes
        else focus_route_sample_tickers(
            tickers,
            paper_queue_tickers,
            execution_rows,
            sample_size=args.focus_route_sample_size,
        )
    )
    execution_results = audit_execution_focus_routes(
        args.base_url,
        focus_route_tickers,
        execution_rows,
        timeout=args.timeout,
        workers=args.workers,
        route_budget_seconds=args.route_budget_seconds,
    )
    candidate_results: list[dict[str, object]] = []
    if args.candidate_pages:
        candidate_tickers = candidate_route_sample_tickers(
            tickers,
            paper_queue_tickers,
            sample_size=args.candidate_page_sample_size,
        )
        row_by_ticker = _row_by_ticker(execution_rows)
        candidate_results = audit_candidate_routes(
            args.base_url,
            candidate_tickers,
            paper_review_queue_tickers=paper_queue_tickers,
            execution_row_by_ticker=row_by_ticker,
            timeout=args.timeout,
            workers=args.workers,
            route_budget_seconds=args.route_budget_seconds,
        )
    final_selection_focus_results = audit_final_selection_focus_routes(
        args.base_url,
        focus_route_sample_tickers(
            tickers,
            paper_queue_tickers,
            execution_rows,
            sample_size=args.focus_route_sample_size,
        ),
        timeout=args.timeout,
        workers=args.workers,
        route_budget_seconds=args.route_budget_seconds,
    )
    final_selection_result = fetch_text(args.base_url, "/final-selection", args.timeout)
    process_state_results = audit_process_state(
        execution_rows,
        paper_review_payload,
        final_selection_result.body,
    )
    approval_rehearsal_results: list[dict[str, object]] = []
    if args.approval_rehearsal:
        approval_rehearsal_results = audit_approval_rehearsal(
            args.base_url,
            paper_review_payload,
            timeout=args.timeout,
        )

    all_results = [
        *key_page_results,
        execution_status_result,
        *data_load_contract_results,
        *data_source_contract_results,
        *scheduler_contract_results,
        *status_contract_results,
        *execution_results,
        *final_selection_focus_results,
        *candidate_results,
        *process_state_results,
        *approval_rehearsal_results,
    ]
    failures = [
        failure
        for result in all_results
        for failure in list(result.get("failures", []))
        if isinstance(failure, dict)
    ]
    failures.extend(command_failures)
    summary = {
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "execution_row_count": len(execution_rows),
        "ticker_count": len(tickers),
        "paper_review_queue_count": len(paper_queue_tickers),
        "data_lane_contract_count": len(data_load_contract_results),
        "source_contract_count": len(data_source_contract_results),
        "scheduler_contract_count": len(scheduler_contract_results),
        "key_page_count": len(key_page_results),
        "execution_status_contract_count": len(status_contract_results),
        "execution_focus_route_count": len(execution_results),
        "execution_focus_route_mode": "all" if args.all_focus_routes else "sample",
        "final_selection_focus_route_count": len(final_selection_focus_results),
        "candidate_route_count": len(candidate_results),
        "approval_rehearsal_count": len(approval_rehearsal_results),
        "failure_count": len(failures),
    }
    report = {
        "schema_version": "0.1.0",
        "summary": summary,
        "failures": failures,
        "results": all_results,
        "command_link_failures": command_failures,
    }
    json_path = output_dir / "user-process-flow-audit.json"
    md_path = output_dir / "user-process-flow-audit.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")
    return 1 if failures else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit live operator process flows across the current universe.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--route-budget-seconds",
        type=float,
        default=0.0,
        help="Fail any audited HTML route slower than this budget. Use 0 to disable.",
    )
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument(
        "--focus-route-sample-size",
        type=int,
        default=24,
        help=(
            "Number of ticker-focused execution pages to GET live. "
            "All tickers are still audited through the status contract."
        ),
    )
    parser.add_argument(
        "--all-focus-routes",
        action="store_true",
        help="GET /execution-preview?ticker=... for every current execution ticker.",
    )
    parser.add_argument(
        "--candidate-pages",
        action="store_true",
        help="Also GET sampled /candidates/{ticker}?audit=light pages.",
    )
    parser.add_argument(
        "--candidate-page-sample-size",
        type=int,
        default=24,
        help="Number of candidate pages to GET when --candidate-pages is enabled. Use 0 for all.",
    )
    parser.add_argument(
        "--approval-rehearsal",
        action="store_true",
        help=(
            "POST one queued research approval and verify the server redirects to "
            "the same ticker on execution preview. This records a real review event."
        ),
    )
    return parser.parse_args(argv)


def audit_key_pages(
    base_url: str,
    timeout: int,
    *,
    route_budget_seconds: float = 0.0,
) -> list[dict[str, object]]:
    return [
        audit_html_route(
            fetch_text(base_url, route, timeout),
            route=route,
            route_budget_seconds=route_budget_seconds,
        )
        for route in KEY_ROUTES
    ]


def audit_execution_focus_routes(
    base_url: str,
    tickers: list[str],
    execution_rows: list[dict[str, object]],
    *,
    timeout: int,
    workers: int,
    route_budget_seconds: float = 0.0,
) -> list[dict[str, object]]:
    row_by_ticker = {str(row.get("ticker") or "").upper(): row for row in execution_rows}
    routes = [
        f"/execution-preview?ticker={quote(ticker)}"
        for ticker in tickers
    ]
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(fetch_text, base_url, route, timeout): ticker
            for ticker, route in zip(tickers, routes, strict=True)
        }
        for future in as_completed(future_map):
            ticker = future_map[future]
            result = future.result()
            route_result = audit_html_route(
                result,
                route=result.route,
                ticker=ticker,
                route_budget_seconds=route_budget_seconds,
            )
            route_result["workflow"] = "execution_focus"
            route_result["api_state"] = row_by_ticker.get(ticker, {})
            route_result["failures"].extend(
                audit_execution_focus_html(ticker, result.body),
            )
            route_result["failures"].extend(
                audit_execution_api_alignment(ticker, result.body, row_by_ticker.get(ticker, {})),
            )
            results.append(route_result)
    return sorted(results, key=lambda item: str(item.get("ticker") or item.get("route")))

def audit_final_selection_focus_routes(
    base_url: str,
    tickers: list[str],
    *,
    timeout: int,
    workers: int,
    route_budget_seconds: float = 0.0,
) -> list[dict[str, object]]:
    routes = [f"/final-selection?ticker={quote(ticker)}" for ticker in tickers]
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(fetch_text, base_url, route, timeout): ticker
            for ticker, route in zip(tickers, routes, strict=True)
        }
        for future in as_completed(future_map):
            ticker = future_map[future]
            result = future.result()
            route_result = audit_html_route(
                result,
                route=result.route,
                ticker=ticker,
                route_budget_seconds=route_budget_seconds,
            )
            route_result["workflow"] = "final_selection_focus"
            route_result["failures"].extend(
                audit_final_selection_focus_html(ticker, result.body),
            )
            results.append(route_result)
    return sorted(results, key=lambda item: str(item.get("ticker") or item.get("route")))

def audit_process_state(
    execution_rows: list[dict[str, object]],
    paper_review_payload: dict[str, object],
    final_selection_html: str,
) -> list[dict[str, object]]:
    review_queue_count = len(paper_review_tickers(paper_review_payload))
    action_row_count = sum(1 for row in execution_rows if row_needs_operator_action(row))
    final_selection_has_cards = 'id="candidate-' in final_selection_html
    failures: list[dict[str, object]] = []
    if not execution_rows:
        failures.append(
            failure(
                "execution_preview_has_no_rows",
                "/status/execution-preview",
                "Execution status returned no ticker rows, so the operator has no review or paper-trade path.",
            )
        )
    if review_queue_count == 0 and action_row_count == 0 and not final_selection_has_cards:
        failures.append(
            failure(
                "no_reviewable_candidates",
                "/final-selection",
                (
                    "No reviewable candidates, execution actions, or final-selection cards "
                    "are visible. Run a runtime cycle before calling the app operator-ready."
                ),
            )
        )
    return [
        {
            "route": "/final-selection",
            "workflow": "process_state",
            "status_code": 200,
            "elapsed_seconds": 0,
            "failures": failures,
        }
    ]


def audit_execution_status_contracts(
    execution_rows: list[dict[str, object]],
    tickers: list[str],
) -> list[dict[str, object]]:
    row_by_ticker = {str(row.get("ticker") or "").upper(): row for row in execution_rows}
    results: list[dict[str, object]] = []
    for ticker in tickers:
        row = row_by_ticker.get(ticker, {})
        failures: list[dict[str, object]] = []
        if not row:
            failures.append(
                failure(
                    "execution_status_row_missing",
                    "/status/execution-preview",
                    f"{ticker} is missing from execution-preview status rows.",
                    ticker=ticker,
                )
            )
        for key in (
            "preview_state",
            "approval_label",
            "paper_promotion_status_label",
            "next_step",
            "order_intent_hash_label",
            "submit_enabled",
            "order_approval_available",
        ):
            if key not in row:
                failures.append(
                    failure(
                        "execution_status_field_missing",
                        "/status/execution-preview",
                        f"{ticker} status row is missing `{key}`.",
                        ticker=ticker,
                    )
                )
        text = json.dumps(row, sort_keys=True)
        for hit in forbidden_ux_hits(text):
            failures.append(
                failure(
                    "old_ux_residue",
                    "/status/execution-preview",
                    f"{ticker} status payload contains forbidden residue term: {hit['term']}.",
                    ticker=ticker,
                    evidence=hit,
                )
            )
        if approved_label(row.get("approval_label")):
            next_step = str(row.get("next_step") or "")
            approved_explained = (
                "Research approval is recorded" in next_step
                or "Acknowledge the caution" in next_step
            )
            if not approved_explained:
                failures.append(
                    failure(
                        "approved_state_has_unclear_next_step",
                        "/status/execution-preview",
                        f"{ticker} is approved but the next step does not say what changed.",
                        ticker=ticker,
                    )
                )
        results.append(
            {
                "route": "/status/execution-preview",
                "ticker": ticker,
                "workflow": "execution_status_contract",
                "status_code": 200 if row else 0,
                "elapsed_seconds": 0,
                "failures": failures,
            }
        )
    return results


def audit_execution_status_payload(
    payload: Mapping[str, object],
    execution_rows: list[dict[str, object]],
) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    if payload.get("available") is not True:
        status_code = payload.get("status_code", "unknown")
        error = str(payload.get("error") or "execution status endpoint did not return JSON")
        failures.append(
            failure(
                "execution_status_unavailable",
                "/status/execution-preview",
                f"Execution status API unavailable: status {status_code}; {error}.",
            )
        )
    elif not execution_rows:
        failures.append(
            failure(
                "execution_status_empty_rows",
                "/status/execution-preview",
                "Execution status API returned JSON but no ticker rows.",
            )
        )
    return {
        "route": "/status/execution-preview",
        "workflow": "execution_status_payload",
        "status_code": int(payload.get("status_code") or 200)
        if payload.get("available") is True
        else int(payload.get("status_code") or 0),
        "elapsed_seconds": 0,
        "failures": failures,
    }


def focus_route_sample_tickers(
    tickers: list[str],
    paper_review_queue_tickers: list[str],
    execution_rows: list[dict[str, object]],
    *,
    sample_size: int,
) -> list[str]:
    if sample_size <= 0 or sample_size >= len(tickers):
        return list(tickers)
    approved = [
        str(row.get("ticker") or "").upper()
        for row in execution_rows
        if approved_label(row.get("approval_label"))
    ]
    ready = [
        str(row.get("ticker") or "").upper()
        for row in execution_rows
        if str(row.get("preview_state") or "") == "READY"
    ]
    selected: list[str] = []
    seen: set[str] = set()
    for ticker in [*approved, *paper_review_queue_tickers, *ready, *tickers]:
        normalized = ticker.strip().upper()
        if normalized and normalized in tickers and normalized not in seen:
            selected.append(normalized)
            seen.add(normalized)
        if len(selected) >= sample_size:
            break
    return selected


def audit_ticker_sample(
    tickers: list[str],
    paper_review_queue_tickers: list[str],
    *,
    max_tickers: int,
) -> list[str]:
    if max_tickers <= 0 or max_tickers >= len(tickers):
        return list(tickers)
    selected: list[str] = []
    seen: set[str] = set()
    for ticker in [*paper_review_queue_tickers, *tickers]:
        normalized = ticker.strip().upper()
        if normalized and normalized in tickers and normalized not in seen:
            selected.append(normalized)
            seen.add(normalized)
        if len(selected) >= max_tickers:
            break
    return selected


def _execution_rows_for_sample(
    execution_rows: list[dict[str, object]],
    tickers: list[str],
) -> list[dict[str, object]]:
    ticker_set = set(tickers)
    return [
        row
        for row in execution_rows
        if str(row.get("ticker") or "").strip().upper() in ticker_set
    ]


def _row_by_ticker(execution_rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        str(row.get("ticker") or "").strip().upper(): row
        for row in execution_rows
        if str(row.get("ticker") or "").strip()
    }


def candidate_route_sample_tickers(
    tickers: list[str],
    paper_review_queue_tickers: list[str],
    *,
    sample_size: int,
) -> list[str]:
    if sample_size <= 0 or sample_size >= len(tickers):
        return list(tickers)
    selected: list[str] = []
    seen: set[str] = set()
    for ticker in [*paper_review_queue_tickers, *tickers]:
        normalized = ticker.strip().upper()
        if normalized and normalized in tickers and normalized not in seen:
            selected.append(normalized)
            seen.add(normalized)
        if len(selected) >= sample_size:
            break
    return selected


def audit_candidate_routes(
    base_url: str,
    tickers: list[str],
    *,
    paper_review_queue_tickers: list[str],
    execution_row_by_ticker: Mapping[str, Mapping[str, object]],
    timeout: int,
    workers: int,
    route_budget_seconds: float = 0.0,
) -> list[dict[str, object]]:
    routes = [f"/candidates/{quote(ticker)}?audit=light" for ticker in tickers]
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(fetch_text, base_url, route, timeout): ticker
            for ticker, route in zip(tickers, routes, strict=True)
        }
        for future in as_completed(future_map):
            ticker = future_map[future]
            result = future.result()
            route_result = audit_html_route(
                result,
                route=result.route,
                ticker=ticker,
                route_budget_seconds=route_budget_seconds,
            )
            route_result["workflow"] = "candidate_detail"
            route_result["failures"].extend(
                audit_candidate_html(
                    ticker,
                    result.body,
                    expect_review_action=(
                        ticker.upper() in set(paper_review_queue_tickers)
                        or row_needs_operator_action(
                            execution_row_by_ticker.get(ticker.upper(), {})
                        )
                    ),
                )
            )
            results.append(route_result)
    return sorted(results, key=lambda item: str(item.get("ticker") or item.get("route")))


def audit_html_route(
    fetch: FetchResult,
    *,
    route: str,
    ticker: str | None = None,
    route_budget_seconds: float = 0.0,
) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    if route_budget_seconds > 0 and fetch.elapsed_seconds > route_budget_seconds:
        failures.append(
            failure(
                "route_budget_exceeded",
                route,
                (
                    f"Route took {fetch.elapsed_seconds:.1f}s, above the "
                    f"{route_budget_seconds:.1f}s operator-flow budget."
                ),
                ticker=ticker,
            )
        )
    if fetch.status_code != 200:
        failures.append(
            failure(
                "http_status",
                route,
                f"Expected HTTP 200, got {fetch.status_code}. {fetch.error}".strip(),
                ticker=ticker,
            )
        )
    if fetch.body:
        if f'data-ux-build="{EXPECTED_V3_BUILD}"' not in fetch.body:
            failures.append(
                failure("missing_v3_build", route, "The current V3 build marker is missing.", ticker=ticker)
            )
        if "v3-app" not in fetch.body:
            failures.append(
                failure("missing_v3_shell", route, "The V3 body shell class is missing.", ticker=ticker)
            )
        if "data-v3-universal-briefing" not in fetch.body:
            failures.append(
                failure("missing_v3_briefing", route, "The V3 BLUF briefing is missing.", ticker=ticker)
            )
        for hit in forbidden_ux_hits(fetch.body):
            failures.append(
                failure(
                    "old_ux_residue",
                    route,
                    f"User-facing page contains forbidden residue term: {hit['term']}.",
                    ticker=ticker,
                    evidence=hit,
                )
            )
        failures.extend(audit_disabled_operator_controls(route, fetch.body, ticker=ticker))
        failures.extend(audit_dashboard_health_html(route, fetch.body, ticker=ticker))
    return {
        "route": route,
        "ticker": ticker or "",
        "status_code": fetch.status_code,
        "elapsed_seconds": round(fetch.elapsed_seconds, 3),
        "failures": failures,
    }


def audit_dashboard_health_html(
    route: str,
    html: str,
    *,
    ticker: str | None = None,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    has_health_panel = "data-health-panel" in html
    has_cockpit_state = "cockpit-data-state-strip" in html
    if route in {"/", "/cockpit"}:
        if not has_health_panel and not has_cockpit_state:
            failures.append(
                failure(
                    "dashboard_health_state_missing",
                    route,
                    (
                        "The first-screen dashboard state lacks displayed data-health "
                        "or cockpit data-state proof."
                    ),
                    ticker=ticker,
                )
            )
        return failures
    if not has_health_panel:
        failures.append(
            failure(
                "dashboard_health_panel_missing",
                route,
                (
                    "Dashboard does not expose the displayed-data health panel used "
                    "by the Cockpit QA method."
                ),
                ticker=ticker,
            )
        )
        return failures
    visible = _visible_text(html)
    for token in ("Displayed Data Health", "What this means", "Recommended action"):
        if token not in visible:
            failures.append(
                failure(
                    "dashboard_health_panel_incomplete",
                    route,
                    f"Displayed-data health panel is missing `{token}`.",
                    ticker=ticker,
                )
            )
    if "Health proof" not in visible and "Last verified" not in visible:
        failures.append(
            failure(
                "dashboard_health_proof_missing",
                route,
                "Displayed-data health panel is missing timestamp/proof wording.",
                ticker=ticker,
            )
        )
    if "Next action" not in visible and "Open Refresh Queue" not in visible:
        failures.append(
            failure(
                "dashboard_health_action_missing",
                route,
                "Displayed-data health panel does not show a concrete next action.",
                ticker=ticker,
            )
        )
    return failures


def audit_data_load_status_contract(payload: Mapping[str, object]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    if payload.get("available") is not True:
        failures.append(
            failure(
                "data_load_status_unavailable",
                "/status/data-load",
                f"Data-load status API unavailable: {payload.get('error') or 'unknown error'}.",
            )
        )
        return [_contract_result("/status/data-load", "data_load_status", failures)]

    lane_states = _mapping_rows(payload.get("lane_states"))
    agent_rows = _mapping_rows(payload.get("lanes"))
    dataset_rows = _mapping_rows(payload.get("datasets"))
    if not lane_states:
        failures.append(
            failure(
                "data_lane_states_missing",
                "/status/data-load",
                (
                    "Data-load status does not expose lane_states, so dashboards "
                    "cannot show per-lane progress/proof."
                ),
            )
        )
    if not agent_rows:
        failures.append(
            failure(
                "agent_process_rows_missing",
                "/status/data-load",
                "Data-load status does not expose agent/process lane rows.",
            )
        )
    if not dataset_rows:
        failures.append(
            failure(
                "dataset_rows_missing",
                "/status/data-load",
                (
                    "Data-load status does not expose dataset rows for the dashboard "
                    "data-health panels."
                ),
            )
        )
    health_monitor = payload.get("health_monitor")
    if not isinstance(health_monitor, Mapping) or not health_monitor:
        failures.append(
            failure(
                "health_monitor_state_missing",
                "/status/data-load",
                "Data-load status does not expose a health-monitor proof object.",
            )
        )
    for lane in lane_states:
        failures.extend(audit_lane_state_contract(lane))
    for row in agent_rows:
        failures.extend(audit_agent_process_contract(row))
    for row in dataset_rows:
        failures.extend(audit_dataset_contract(row))
    return [_contract_result("/status/data-load", "data_load_status", failures)]


def audit_lane_state_contract(row: Mapping[str, object]) -> list[dict[str, object]]:
    route = "/status/data-load"
    lane_id = str(row.get("lane_id") or "unknown_lane")
    failures = _required_field_failures(
        row,
        LANE_STATE_REQUIRED_FIELDS,
        route=route,
        code="lane_state_field_missing",
        subject=lane_id,
    )
    progress = row.get("progress_percent")
    if not isinstance(progress, int) or progress < 0 or progress > 100:
        failures.append(
            failure(
                "lane_state_progress_invalid",
                route,
                f"{lane_id} progress_percent must be an integer from 0 to 100.",
                ticker=lane_id,
                evidence={"progress_percent": progress},
            )
        )
    if _is_missing_proof(row.get("checked_at")):
        failures.append(
            failure(
                "lane_state_proof_timestamp_missing",
                route,
                f"{lane_id} lacks checked_at proof for its displayed state.",
                ticker=lane_id,
            )
        )
    state = str(row.get("state") or "").casefold()
    action_text = str(row.get("recommended_action") or "").casefold()
    if state in {
        "loading",
        "loaded_unanalyzed",
        "needs_refresh",
        "provider_unavailable",
    } and not any(marker in action_text for marker in ACTIONABLE_STATE_MARKERS):
        failures.append(
            failure(
                "lane_state_action_not_operator_clear",
                route,
                f"{lane_id} is {state or 'not ready'} but lacks a concrete operator action.",
                ticker=lane_id,
            )
        )
    refresh_available = row.get("refresh_action_available") is True
    if refresh_available:
        for key in ("refresh_action_label", "refresh_action_url", "refresh_action_method"):
            if _is_missing_proof(row.get(key)):
                failures.append(
                    failure(
                        "lane_refresh_action_incomplete",
                        route,
                        f"{lane_id} exposes a refresh action but `{key}` is missing.",
                        ticker=lane_id,
                    )
                )
    elif _is_missing_proof(row.get("refresh_action_disabled_reason")) and _is_missing_proof(
        row.get("refresh_action_detail")
    ):
        failures.append(
            failure(
                "lane_refresh_disabled_reason_missing",
                route,
                f"{lane_id} lacks a disabled reason for the missing direct refresh action.",
                ticker=lane_id,
            )
        )
    failures.extend(_operator_copy_forbidden_failures(row, lane_id, route=route))
    return failures


def audit_agent_process_contract(row: Mapping[str, object]) -> list[dict[str, object]]:
    route = "/status/data-load"
    lane = str(row.get("lane") or "unknown_agent")
    failures = _required_field_failures(
        row,
        AGENT_ROW_REQUIRED_FIELDS,
        route=route,
        code="agent_process_field_missing",
        subject=lane,
    )
    detail = str(row.get("detail") or "")
    status_class = str(row.get("status_class") or "").casefold()
    if status_class in {"warn", "warning", "block"} and len(detail.strip()) < 40:
        failures.append(
            failure(
                "agent_process_reason_too_vague",
                route,
                f"{lane} is not fully ready but its detail is too short to explain the issue.",
                ticker=lane,
            )
        )
    failures.extend(_operator_copy_forbidden_failures(row, lane, route=route))
    return failures


def audit_dataset_contract(row: Mapping[str, object]) -> list[dict[str, object]]:
    route = "/status/data-load"
    dataset = str(row.get("dataset") or "unknown_dataset")
    failures = _required_field_failures(
        row,
        DATASET_ROW_REQUIRED_FIELDS,
        route=route,
        code="dataset_field_missing",
        subject=dataset,
    )
    detail = str(row.get("detail") or "")
    status_class = str(row.get("status_class") or "").casefold()
    if status_class in {"warn", "warning", "block"} and len(detail.strip()) < 40:
        failures.append(
            failure(
                "dataset_reason_too_vague",
                route,
                f"{dataset} is not fully ready but its detail is too short to explain the issue.",
                ticker=dataset,
            )
        )
    failures.extend(_operator_copy_forbidden_failures(row, dataset, route=route))
    return failures


def audit_data_sources_contract(payload: Mapping[str, object]) -> list[dict[str, object]]:
    route = "/status/data-sources"
    rows = _mapping_rows(payload.get("payload")) if "payload" in payload else _mapping_rows(payload)
    failures: list[dict[str, object]] = []
    if payload.get("available") is not True and "payload" in payload:
        failures.append(
            failure(
                "data_sources_unavailable",
                route,
                f"Data-source status API unavailable: {payload.get('error') or 'unknown error'}.",
            )
        )
    if not rows:
        failures.append(
            failure(
                "data_sources_empty",
                route,
                "Data-source status endpoint returned no provider rows.",
            )
        )
    for row in rows:
        source = str(row.get("source") or "unknown_source")
        for key in ("source", "status", "freshness", "checked_at"):
            if _is_missing_proof(row.get(key)):
                failures.append(
                    failure(
                        "data_source_field_missing",
                        route,
                        f"{source} source-health row is missing `{key}`.",
                        ticker=source,
                    )
                )
    return [_contract_result(route, "data_sources", failures)]


def audit_scheduler_status_contract(payload: Mapping[str, object]) -> list[dict[str, object]]:
    route = "/status/scheduler-work-queue"
    failures: list[dict[str, object]] = []
    if payload.get("available") is not True:
        failures.append(
            failure(
                "scheduler_status_unavailable",
                route,
                f"Scheduler status API unavailable: {payload.get('error') or 'unknown error'}.",
            )
        )
        return [_contract_result(route, "scheduler_status", failures)]
    for key in ("headline", "status_label", "status_class"):
        if _is_missing_proof(payload.get(key)):
            failures.append(
                failure(
                    "scheduler_status_field_missing",
                    route,
                    f"Scheduler status payload is missing `{key}`.",
                )
            )
    detail_text = " ".join(
        str(payload.get(key) or "")
        for key in ("headline", "tradability_detail", "detail")
    )
    if len(detail_text.strip()) < 30:
        failures.append(
            failure(
                "scheduler_status_reason_too_vague",
                route,
                "Scheduler status does not explain what is usable, loading, or blocked.",
            )
        )
    orchestrator = payload.get("massive_orchestrator")
    if isinstance(orchestrator, Mapping):
        lane_rows = [
            *_mapping_rows(orchestrator.get("lanes")),
            *_mapping_rows(orchestrator.get("raw_lanes")),
            *_mapping_rows(orchestrator.get("derived_signal_lanes")),
        ]
        for row in lane_rows:
            lane_id = str(row.get("lane_id") or row.get("lane") or "unknown_scheduler_lane")
            for key in ("status_label", "status_class", "detail"):
                if _is_missing_proof(row.get(key)):
                    failures.append(
                        failure(
                            "scheduler_lane_field_missing",
                            route,
                            f"{lane_id} scheduler lane row is missing `{key}`.",
                            ticker=lane_id,
                        )
                    )
    return [_contract_result(route, "scheduler_status", failures)]


def _contract_result(
    route: str,
    workflow: str,
    failures: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "route": route,
        "workflow": workflow,
        "status_code": 200 if not failures else 0,
        "elapsed_seconds": 0,
        "failures": failures,
    }


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _required_field_failures(
    row: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    route: str,
    code: str,
    subject: str,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for field in fields:
        if _is_missing_proof(row.get(field)):
            failures.append(
                failure(
                    code,
                    route,
                    f"{subject} is missing `{field}`.",
                    ticker=subject,
                )
            )
    return failures


def _operator_copy_forbidden_failures(
    row: Mapping[str, object],
    subject: str,
    *,
    route: str,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for field in OPERATOR_STATE_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        for hit in forbidden_ux_hits(str(value)):
            failures.append(
                failure(
                    "operator_copy_forbidden_term",
                    route,
                    f"{subject} operator-facing `{field}` contains forbidden term: {hit['term']}.",
                    ticker=subject,
                    evidence=hit,
                )
            )
    return failures


def _is_missing_proof(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.casefold() in {"none", "null", "not recorded", "not checked"}


def audit_execution_focus_html(ticker: str, html: str) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    normalized = ticker.upper()
    selected_marker = f'data-selected-ticker="{normalized}"'
    focused_anchor = f'id="focused-preview-{normalized}"'
    followup_heading = 'id="execution-followup-heading"'
    if selected_marker not in html:
        failures.append(
            failure(
                "execution_focus_missing_selected_ticker",
                "/execution-preview",
                f"{normalized} is not preserved in the selected-ticker panel.",
                ticker=normalized,
            )
        )
    if f"{normalized} Follow-Up" not in html:
        failures.append(
            failure(
                "execution_focus_missing_heading",
                "/execution-preview",
                f"The focused {normalized} follow-up heading is missing.",
                ticker=normalized,
            )
        )
    focused_index = html.find(focused_anchor)
    generic_index = html.find(followup_heading)
    if focused_index < 0:
        failures.append(
            failure(
                "execution_focus_missing_card",
                "/execution-preview",
                f"The focused card anchor for {normalized} is missing.",
                ticker=normalized,
            )
        )
    elif generic_index >= 0 and focused_index > generic_index:
        failures.append(
            failure(
                "execution_focus_buried",
                "/execution-preview",
                f"The focused {normalized} card appears after the generic execution list.",
                ticker=normalized,
            )
        )
    return failures

def audit_final_selection_focus_html(ticker: str, html: str) -> list[dict[str, object]]:
    normalized = ticker.upper()
    failures: list[dict[str, object]] = []
    focused_anchor = f'id="candidate-{normalized}"'
    if focused_anchor not in html:
        if "No final selection reports yet" in html:
            failures.append(
                failure(
                    "final_selection_focus_has_no_candidates",
                    "/final-selection",
                    (
                        f"{normalized} was requested from the workflow, but the "
                        "final-selection page rendered the empty state."
                    ),
                    ticker=normalized,
                )
            )
        else:
            failures.append(
                failure(
                    "final_selection_focus_missing_candidate",
                    "/final-selection",
                    f"{normalized} focused candidate card is missing.",
                    ticker=normalized,
                )
            )
    if f"Approve research for {normalized}" not in html and f"{normalized} candidate" not in html:
        failures.append(
            failure(
                "final_selection_focus_missing_action_copy",
                "/final-selection",
                f"{normalized} final-selection focus lacks ticker-specific next-action copy.",
                ticker=normalized,
            )
        )
    return failures

def row_needs_operator_action(row: Mapping[str, object]) -> bool:
    return any(
        row.get(key) is True
        for key in (
            "research_approval_available",
            "operator_manual_advance_available",
            "order_approval_available",
            "submit_enabled",
        )
    )

def approved_label(value: object) -> bool:
    return "approved" in str(value or "").casefold()


def audit_execution_api_alignment(
    ticker: str,
    html: str,
    row: dict[str, object],
) -> list[dict[str, object]]:
    if not row:
        return [
            failure(
                "execution_api_row_missing",
                "/status/execution-preview",
                f"{ticker} is not present in execution-preview status rows.",
                ticker=ticker,
            )
        ]
    failures: list[dict[str, object]] = []
    approval_label = str(row.get("approval_label") or "")
    reason = str(next(iter(row.get("paper_promotion_reasons") or []), ""))
    if approved_label(approval_label) and f"{ticker} research approval is recorded." not in html:
        failures.append(
            failure(
                "approval_state_not_reflected",
                "/execution-preview",
                f"{ticker} is approved in the status API but not explained as approved in the focused page.",
                ticker=ticker,
            )
        )
    if row.get("submit_enabled") is True:
        for token in (
            'action="/execution-preview/orders?',
            'name="submit_gate_armed"',
            'name="operator_phrase"',
            "submit paper orders",
        ):
            if token not in html:
                failures.append(
                    failure(
                        "submit_ready_action_missing",
                        "/execution-preview",
                        f"{ticker} is submit-ready in the API but the focused page lacks `{token}`.",
                        ticker=ticker,
                    )
                )
    if reason and reason not in html:
        failures.append(
            failure(
                "promotion_reason_not_visible",
                "/execution-preview",
                f"{ticker} focused page does not show the API blocker: {reason}",
                ticker=ticker,
            )
        )
    return failures


def audit_candidate_html(
    ticker: str,
    html: str,
    *,
    expect_review_action: bool = True,
) -> list[dict[str, object]]:
    normalized = ticker.upper()
    failures: list[dict[str, object]] = []
    if (
        expect_review_action
        and f"/candidates/{normalized}/reviews?" not in html
        and "Review recorded" not in html
        and not candidate_analysis_refresh_state_visible(html)
    ):
        failures.append(
            failure(
                "candidate_review_action_missing",
                f"/candidates/{normalized}",
                f"{normalized} candidate detail has neither review actions nor recorded-review state.",
                ticker=normalized,
            )
        )
    if "data-health-panel" not in html:
        failures.append(
            failure(
                "candidate_data_health_missing",
                f"/candidates/{normalized}",
                f"{normalized} candidate detail does not expose data-health proof.",
                ticker=normalized,
            )
        )
    else:
        for token in ("Cycle", "Last verified", "Recommended action"):
            if token not in html:
                failures.append(
                    failure(
                        "candidate_data_health_proof_incomplete",
                        f"/candidates/{normalized}",
                        f"{normalized} data-health panel is missing `{token}` proof.",
                        ticker=normalized,
                    )
                )
    return failures


def candidate_analysis_refresh_state_visible(html: str) -> bool:
    normalized = re.sub(r"\s+", " ", html).casefold()
    has_currentness_explanation = (
        "previous report rows are not used as current evidence" in normalized
        or "current report details are hidden until analysis is ready" in normalized
        or "approval is disabled until the current analysis finishes" in normalized
    )
    has_operator_next_step = (
        "refresh live trade slices" in normalized
        or "matching lane refresh control" in normalized
        or "open refresh queue" in normalized
    )
    has_health_proof = "displayed data health" in normalized and "recommended action" in normalized
    return has_currentness_explanation and has_operator_next_step and has_health_proof


def audit_command_links(html: str, tickers: list[str]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for ticker in tickers:
        expected = f'href="/execution-preview?ticker={ticker}#focused-preview-{ticker}"'
        if expected not in html:
            failures.append(
                failure(
                    "command_execute_link_loses_ticker",
                    "/command",
                    f"Command review queue execute link for {ticker} does not preserve ticker focus.",
                    ticker=ticker,
                )
            )
    return failures


_CONTROL_RE = re.compile(
    r"<(?P<tag>a|button)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_ATTR_RE = re.compile(r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.DOTALL)
_REASON_MARKERS = (
    "reason",
    "because",
    "requires",
    "required",
    "wait",
    "refresh",
    "not ready",
    "not available",
    "unavailable",
    "approval",
    "approved",
    "broker",
    "api key",
    "data is still loading",
    "needs refresh",
    "login",
    "select",
    "no paper order",
    "next step",
)


def audit_disabled_operator_controls(
    route: str,
    html: str,
    *,
    ticker: str | None = None,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for match in _CONTROL_RE.finditer(html):
        attrs = match.group("attrs") or ""
        if not _control_is_disabled(attrs):
            continue
        button_text = _visible_text(match.group("body"))
        if not button_text and _attr(attrs, "aria-hidden").lower() == "true":
            continue
        context = html[max(0, match.start() - 700) : min(len(html), match.end() + 700)]
        if _disabled_control_has_reason(attrs, context):
            continue
        failures.append(
            failure(
                "disabled_control_missing_reason",
                route,
                (
                    "A disabled operator button is visible without a nearby plain-English "
                    "reason or next step."
                ),
                ticker=ticker,
                evidence={
                    "button_text": button_text or "(icon-only button)",
                    "excerpt": _visible_text(context)[:500],
                },
            )
        )
    return failures


def _control_is_disabled(attrs: str) -> bool:
    class_attr = _attr(attrs, "class").casefold()
    aria_disabled = _attr(attrs, "aria-disabled").casefold()
    attrs_without_values = re.sub(
        r"=\s*(?P<quote>['\"]).*?(?P=quote)",
        "",
        attrs,
        flags=re.DOTALL,
    ).casefold()
    return bool(
        re.search(r"(^|\s)disabled(\s|=|$)", attrs_without_values)
        or aria_disabled == "true"
        or "disabled-button" in class_attr
        or "primary-action-disabled" in class_attr
    )


def _disabled_control_has_reason(attrs: str, context: str) -> bool:
    attribute_proof = " ".join(
        _attr(attrs, name)
        for name in (
            "title",
            "aria-label",
            "data-disabled-reason",
            "data-reason",
            "data-next-step",
        )
    )
    text = f"{attribute_proof} {_visible_text(context)}".casefold()
    return any(marker in text for marker in _REASON_MARKERS)


def _attr(attrs: str, name: str) -> str:
    target = name.casefold()
    for match in _ATTR_RE.finditer(attrs):
        if match.group("name").casefold() == target:
            return html_lib.unescape(match.group("value")).strip()
    return ""


def _visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG_RE.sub(" ", html))).strip()


def audit_approval_rehearsal(
    base_url: str,
    paper_review_payload: Mapping[str, object],
    *,
    timeout: int,
) -> list[dict[str, object]]:
    row = _approval_rehearsal_row(paper_review_payload)
    if not row:
        return [
            {
                "route": "/status/paper-review",
                "workflow": "approval_rehearsal",
                "status_code": 0,
                "elapsed_seconds": 0,
                "failures": [
                    failure(
                        "approval_rehearsal_no_candidate",
                        "/status/paper-review",
                        "No queued candidate exposes an approval action for the POST rehearsal.",
                    )
                ],
            }
        ]
    ticker = str(row.get("ticker") or "").strip().upper()
    action = _approval_rehearsal_action(row)
    post_result = post_form(
        base_url,
        action,
        timeout,
        data={"caution_acknowledged": "true"},
    )
    failures = audit_approval_post_result(ticker, post_result)
    return [
        {
            "route": post_result.route,
            "ticker": ticker,
            "workflow": "approval_rehearsal",
            "status_code": post_result.status_code,
            "elapsed_seconds": round(post_result.elapsed_seconds, 3),
            "redirect_location": post_result.location,
            "failures": failures,
        }
    ]


def _approval_rehearsal_row(payload: Mapping[str, object]) -> dict[str, object]:
    rows = payload.get("queue") or []
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker and _approval_rehearsal_action(row):
            return dict(row)
    return {}


def _approval_rehearsal_action(row: Mapping[str, object]) -> str:
    action = str(row.get("approve_review_action") or row.get("approve_action") or "").strip()
    if action:
        return html_lib.unescape(action)
    ticker = str(row.get("ticker") or "").strip().upper()
    cycle_id = str(row.get("cycle_id") or "").strip()
    as_of = str(row.get("as_of") or "").strip()
    if not ticker or not cycle_id or not as_of:
        return ""
    query = urlencode(
        {
            "cycle_id": cycle_id,
            "as_of": as_of,
            "decision": "APPROVE",
            "caution_acknowledged": "true",
        }
    )
    return f"/candidates/{quote(ticker)}/reviews?{query}"


def audit_approval_post_result(
    ticker: str,
    post_result: PostResult,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    expected = f"/execution-preview?ticker={quote(ticker)}#focused-preview-{quote(ticker)}"
    if post_result.status_code not in {302, 303}:
        failures.append(
            failure(
                "approval_rehearsal_post_failed",
                post_result.route,
                (
                    f"Approval rehearsal expected a 302/303 redirect, got "
                    f"{post_result.status_code}. {post_result.error}".strip()
                ),
                ticker=ticker,
            )
        )
        return failures
    if _normalize_location(post_result.location) != expected:
        failures.append(
            failure(
                "approval_rehearsal_lost_ticker_focus",
                post_result.route,
                (
                    f"Approval redirect should land on `{expected}`, got "
                    f"`{post_result.location or '(no location header)'}`."
                ),
                ticker=ticker,
            )
        )
    return failures


def _normalize_location(location: str) -> str:
    parts = urlsplit(location)
    if parts.scheme or parts.netloc:
        query = urlencode(parse_qsl(parts.query, keep_blank_values=True))
        return urlunsplit(("", "", parts.path, query, parts.fragment))
    return location


def forbidden_ux_hits(text: str) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for term, pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        start = max(0, match.start() - 60)
        end = min(len(text), match.end() + 60)
        hits.append(
            {
                "term": term,
                "excerpt": re.sub(r"\s+", " ", text[start:end]).strip(),
            }
        )
    return hits


def status_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("rows") or payload.get("preview_rows") or []
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def status_tickers(payload: dict[str, object]) -> list[str]:
    tickers = {
        str(row.get("ticker") or "").strip().upper()
        for row in status_rows(payload)
    }
    return sorted(ticker for ticker in tickers if ticker)


def paper_review_tickers(payload: dict[str, object]) -> list[str]:
    queue = payload.get("queue") or []
    if not isinstance(queue, list):
        return []
    return [
        str(row.get("ticker") or "").strip().upper()
        for row in queue
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    ]


def json_get(base_url: str, route: str, timeout: int) -> dict[str, object]:
    last_payload: dict[str, object] | None = None
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        result = fetch_text(base_url, route, timeout, accept="application/json")
        if result.status_code != 200:
            last_payload = {
                "available": False,
                "status_code": result.status_code,
                "error": result.error,
            }
        else:
            try:
                payload = json.loads(result.body)
            except json.JSONDecodeError as exc:
                last_payload = {"available": False, "error": str(exc)}
            else:
                if isinstance(payload, dict):
                    payload.setdefault("available", True)
                    last_payload = payload
                else:
                    last_payload = {"available": True, "payload": payload}
        if last_payload is None or not _json_payload_needs_retry(last_payload):
            return last_payload or {"available": False, "error": "empty status response"}
        if attempt < max_attempts:
            time.sleep(1.0 * attempt)
    return last_payload or {"available": False, "error": "empty status response"}


def _json_payload_needs_retry(payload: Mapping[str, object]) -> bool:
    if payload.get("available") is not True:
        return False
    verdict = str(payload.get("verdict") or "").casefold()
    status = str(payload.get("status") or "").casefold()
    status_label = str(payload.get("status_label") or "").casefold()
    headline = str(payload.get("headline") or "").casefold()
    return (
        verdict == "status_timeout"
        or status == "status_delayed"
        or "status delayed" in status_label
        or "still loading" in headline
    )


def fetch_text(
    base_url: str,
    route: str,
    timeout: int,
    *,
    accept: str = "text/html",
) -> FetchResult:
    last_result = FetchResult(route, 0, "", 0.0, "request not attempted")
    url = urljoin(base_url.rstrip("/") + "/", route.lstrip("/"))
    headers = {"Accept": accept}
    for attempt in range(1, 4):
        start = time.perf_counter()
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            return FetchResult(
                route,
                int(response.status_code),
                response.text,
                time.perf_counter() - start,
                "" if response.ok else response.reason,
            )
        except requests.RequestException as exc:
            last_result = FetchResult(
                route,
                0,
                "",
                time.perf_counter() - start,
                f"{exc} (attempt {attempt}/3)",
            )
            if attempt < 3:
                time.sleep(0.5 * attempt)
    return last_result


def post_form(
    base_url: str,
    route: str,
    timeout: int,
    *,
    data: Mapping[str, str],
) -> PostResult:
    normalized_route = html_lib.unescape(route)
    url = urljoin(base_url.rstrip("/") + "/", normalized_route.lstrip("/"))
    start = time.perf_counter()
    try:
        response = requests.post(
            url,
            data=dict(data),
            timeout=timeout,
            allow_redirects=False,
        )
        return PostResult(
            normalized_route,
            int(response.status_code),
            str(response.headers.get("Location") or ""),
            response.text,
            time.perf_counter() - start,
            "" if response.ok or response.is_redirect else response.reason,
        )
    except requests.RequestException as exc:
        return PostResult(
            normalized_route,
            0,
            "",
            "",
            time.perf_counter() - start,
            str(exc),
        )


def failure(
    code: str,
    route: str,
    detail: str,
    *,
    ticker: str | None = None,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    output: dict[str, object] = {
        "code": code,
        "route": route,
        "ticker": ticker or "",
        "detail": detail,
    }
    if evidence:
        output["evidence"] = evidence
    return output


def markdown_report(report: dict[str, object]) -> str:
    summary = dict(report.get("summary") or {})
    failures = report.get("failures") or []
    lines = [
        "# User Process Flow Audit",
        "",
        "## Summary",
        "",
        f"- Base URL: `{summary.get('base_url', '')}`",
        f"- Execution rows audited: {summary.get('execution_row_count', 0)}",
        f"- Tickers audited: {summary.get('ticker_count', 0)}",
        f"- Execution status contracts: {summary.get('execution_status_contract_count', 0)}",
        f"- Data/agent/lane contract checks: {summary.get('data_lane_contract_count', 0)}",
        f"- Source contract checks: {summary.get('source_contract_count', 0)}",
        f"- Scheduler/process contract checks: {summary.get('scheduler_contract_count', 0)}",
        f"- Focused execution routes: {summary.get('execution_focus_route_count', 0)}",
        f"- Focus route mode: {summary.get('execution_focus_route_mode', '')}",
        f"- Candidate pages: {summary.get('candidate_route_count', 0)}",
        f"- Approval POST rehearsals: {summary.get('approval_rehearsal_count', 0)}",
        f"- Failure count: {summary.get('failure_count', 0)}",
        "",
        "## Findings",
        "",
    ]
    if not failures:
        lines.append("No process-flow failures were detected by this audit run.")
    else:
        for index, item in enumerate(failures, start=1):
            if not isinstance(item, dict):
                continue
            ticker = f" `{item.get('ticker')}`" if item.get("ticker") else ""
            lines.append(
                f"{index}. **{item.get('code')}**{ticker} on `{item.get('route')}` - "
                f"{item.get('detail')}"
            )
    lines.extend(
        [
            "",
            "## Audit Contract",
            "",
            "- Every current execution ticker must preserve focus on `/execution-preview?ticker=TICKER`.",
            "- Focused ticker follow-up must render before the generic execution list.",
            "- Command review-queue execute links must carry ticker focus.",
            "- Candidate detail pages must expose review controls only when the ticker is in the review queue or the status API says operator action is available.",
            "- Approval rehearsal, when enabled, must POST a real review and redirect to the same ticker on execution preview.",
            "- Disabled operator buttons must explain the reason and the next action near the control.",
            "- Every dashboard must expose displayed-data health proof, plain meaning, and an action.",
            "- Every data lane must expose state, progress, ETA, timestamp proof, source proof, and refresh guidance.",
            "- Every agent/process lane must expose source dataset, analysis state, coverage, concrete detail, and proof.",
            "- Scheduler and provider statuses must expose whether work is loading, usable, unavailable, or needs refresh.",
            "- V3 build marker, V3 shell, and BLUF briefing must be present on audited pages.",
            "- User-facing pages must not expose old/test UX residue terms.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
