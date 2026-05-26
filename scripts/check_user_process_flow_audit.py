from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

EXPECTED_V3_BUILD = "ux-v3-all-dashboards-20260523"
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()

    execution_payload = json_get(args.base_url, "/status/execution-preview", args.timeout)
    paper_review_payload = json_get(args.base_url, "/status/paper-review", args.timeout)
    execution_rows = status_rows(execution_payload)
    execution_status_result = audit_execution_status_payload(
        execution_payload,
        execution_rows,
    )
    tickers = status_tickers(execution_payload)
    if args.max_tickers > 0:
        tickers = tickers[: args.max_tickers]

    key_page_results = audit_key_pages(
        args.base_url,
        args.timeout,
        route_budget_seconds=args.route_budget_seconds,
    )
    command_result = fetch_text(args.base_url, "/command", args.timeout)
    if command_result.status_code == 200:
        command_failures = audit_command_links(
            command_result.body,
            paper_review_tickers(paper_review_payload),
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
            paper_review_tickers(paper_review_payload),
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
            paper_review_tickers(paper_review_payload),
            sample_size=args.candidate_page_sample_size,
        )
        candidate_results = audit_candidate_routes(
            args.base_url,
            candidate_tickers,
            timeout=args.timeout,
            workers=args.workers,
            route_budget_seconds=args.route_budget_seconds,
        )
    final_selection_focus_results = audit_final_selection_focus_routes(
        args.base_url,
        focus_route_sample_tickers(
            tickers,
            paper_review_tickers(paper_review_payload),
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

    all_results = [
        *key_page_results,
        execution_status_result,
        *status_contract_results,
        *execution_results,
        *final_selection_focus_results,
        *candidate_results,
        *process_state_results,
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
        "paper_review_queue_count": len(paper_review_tickers(paper_review_payload)),
        "key_page_count": len(key_page_results),
        "execution_status_contract_count": len(status_contract_results),
        "execution_focus_route_count": len(execution_results),
        "execution_focus_route_mode": "all" if args.all_focus_routes else "sample",
        "final_selection_focus_route_count": len(final_selection_focus_results),
        "candidate_route_count": len(candidate_results),
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
            route_result["failures"].extend(audit_candidate_html(ticker, result.body))
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
    return {
        "route": route,
        "ticker": ticker or "",
        "status_code": fetch.status_code,
        "elapsed_seconds": round(fetch.elapsed_seconds, 3),
        "failures": failures,
    }


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


def audit_candidate_html(ticker: str, html: str) -> list[dict[str, object]]:
    normalized = ticker.upper()
    failures: list[dict[str, object]] = []
    if f"/candidates/{normalized}/reviews?" not in html and "Review recorded" not in html:
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
    result = fetch_text(base_url, route, timeout, accept="application/json")
    if result.status_code != 200:
        return {
            "available": False,
            "status_code": result.status_code,
            "error": result.error,
        }
    try:
        payload = json.loads(result.body)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": str(exc)}
    if isinstance(payload, dict):
        payload.setdefault("available", True)
        return payload
    return {"available": True, "payload": payload}


def fetch_text(
    base_url: str,
    route: str,
    timeout: int,
    *,
    accept: str = "text/html",
) -> FetchResult:
    last_result = FetchResult(route, 0, "", 0.0, "request not attempted")
    for attempt in range(1, 4):
        start = time.perf_counter()
        url = urljoin(base_url.rstrip("/") + "/", route.lstrip("/"))
        request = Request(url, headers={"Accept": accept, "Connection": "close"})
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                status_code = int(response.status)
            return FetchResult(route, status_code, body, time.perf_counter() - start)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            status_code = int(exc.code)
            return FetchResult(route, status_code, body, time.perf_counter() - start, str(exc))
        except (OSError, URLError) as exc:
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
        f"- Focused execution routes: {summary.get('execution_focus_route_count', 0)}",
        f"- Focus route mode: {summary.get('execution_focus_route_mode', '')}",
        f"- Candidate pages: {summary.get('candidate_route_count', 0)}",
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
            "- V3 build marker, V3 shell, and BLUF briefing must be present on audited pages.",
            "- User-facing pages must not expose old/test UX residue terms.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
