from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

PAGES = (
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
)
FORBIDDEN_TERMS = (
    "bootstrap",
    "Health Monitor Fallback",
    "Fallback Thesis",
    "Fallback Analysis",
    "Sample:",
    "recent mailbox sample",
    "first-version",
    "demo",
    "mock",
    "fake",
    "fixture",
    "monkey",
)
_FORBIDDEN_TERM_PATTERNS = tuple(
    (
        term,
        re.compile(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"),
    )
    for term in FORBIDDEN_TERMS
)
VIEWPORTS = (
    ("desktop", {"width": 1440, "height": 1100}),
    ("mobile", {"width": 390, "height": 900}),
)
PAGE_LOAD_STATE = "domcontentloaded"
PAGE_LOAD_TIMEOUT_MS = 60_000
BODY_TIMEOUT_MS = 10_000
PAGE_LOAD_ATTEMPTS = 2
PAGE_RETRY_DELAY_MS = 1_000
BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = 45
JSON_GET_ATTEMPTS = 3
JSON_RETRY_DELAY_SECONDS = 1
FULL_READINESS_SCOPE = "full"
REVIEW_SUBSET_READINESS_SCOPE = "review-subset"
EXPECTED_V3_BUILD = "ux-v3-cockpit-primary-20260601"
COCKPIT_ROUTES = {"/", "/cockpit"}
DEFAULT_BRIEFING_SNIPPETS = (
    "Start with the first action card",
    "This screen must show current source proof",
    "Pre-flight review",
)
CONTEXT_DATA_WARNING_ITEMS = {
    "news_rss",
    "subscription_emails",
    "news",
    "subscription_thesis",
}
CONTEXT_DATA_WARNING_KINDS = {"dataset", "agent_lane"}
OPERATIONAL_PAYLOAD_ENDPOINTS = (
    "/reports/selection",
    "/risk/decisions",
)
OPERATIONAL_PAYLOAD_FORBIDDEN_TOKENS = (
    "runtime_" "artifact_" "fallback",
    "demo",
    "mock",
    "fake",
    "fixture",
    "manual-smoke",
    "monkey",
)
_OPERATIONAL_PAYLOAD_PATTERNS = tuple(
    (
        token,
        re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", re.IGNORECASE),
    )
    for token in OPERATIONAL_PAYLOAD_FORBIDDEN_TOKENS
)


def main() -> int:
    args = _parse_args()
    output_dir = Path("research/results/latest-ui-live-data-qa")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    operational_readiness_failures = _operational_readiness_failures(
        BASE_URL,
        readiness_scope=args.readiness_scope,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for viewport_name, viewport in VIEWPORTS:
                for route in PAGES:
                    page = browser.new_page(viewport=viewport)
                    try:
                        name = (
                            "cockpit-root"
                            if route == "/"
                            else route.strip("/").replace("/", "-")
                        )
                        result = _empty_result(viewport_name, route)
                        result["operational_readiness_failures"] = list(
                            operational_readiness_failures
                        )
                        try:
                            body = _load_page_body(page, f"{BASE_URL}{route}")
                            result["forbidden_hits"] = _forbidden_term_hits(body)
                            result["horizontal_overflow"] = bool(
                                page.evaluate(
                                    "document.documentElement.scrollWidth > "
                                    "document.documentElement.clientWidth"
                                )
                            )
                            result["clipped_controls"] = page.evaluate(
                                """
                                () => Array.from(
                                  document.querySelectorAll(
                                    '.tag, button, a.primary-action, a.secondary-action'
                                  )
                                )
                                .filter((el) =>
                                  el.scrollWidth > el.clientWidth + 1 ||
                                  el.scrollHeight > el.clientHeight + 1
                                )
                                .map((el) => el.textContent.trim())
                                .slice(0, 8)
                                """
                            )
                            health_panel_count = page.locator(".data-health-panel").count()
                            health_rows_count = page.locator(".data-health-row").count()
                            result["health_visible"] = health_panel_count > 0
                            result["health_panel_count"] = health_panel_count
                            result["health_rows_count"] = health_rows_count
                            cockpit_data_state = page.locator(
                                ".cockpit-data-state-strip"
                            ).first
                            result["cockpit_data_state_visible"] = (
                                route in COCKPIT_ROUTES
                                and cockpit_data_state.count() > 0
                                and cockpit_data_state.is_visible()
                            )
                            result["cockpit_lane_rows_count"] = page.locator(
                                ".cockpit-lane-row:not(.cockpit-lane-head)"
                            ).count()
                            result["health_rows_missing_fields"] = page.evaluate(
                                """
                                () => Array.from(document.querySelectorAll('.data-health-row'))
                                  .map((row) => {
                                    const text = row.textContent || '';
                                    const hasStatus = row.querySelector('.tag') !== null;
                                    const hasCoverage = text.includes('Coverage');
                                    const hasFreshness = text.includes('Freshness');
                                    const hasLastUpdate = text.includes('Last update');
                                    return hasStatus && hasCoverage && hasFreshness && hasLastUpdate
                                      ? null
                                      : text.trim().replace(/\\s+/g, ' ').slice(0, 120);
                                  })
                                  .filter(Boolean)
                                  .slice(0, 8)
                                """
                            )
                            result["cockpit_lane_rows_missing_fields"] = page.evaluate(
                                """
                                () => Array.from(
                                  document.querySelectorAll(
                                    '.cockpit-lane-row:not(.cockpit-lane-head)'
                                  )
                                )
                                .map((row) => {
                                  const text = row.textContent || '';
                                  const cells = Array.from(row.querySelectorAll('[role="cell"]'));
                                  const progressText = cells[2]?.textContent || '';
                                  const proofText = cells[5]?.textContent || '';
                                  const actionText = cells[6]?.textContent || '';
                                  const hasStatus = row.querySelector('.status-pill') !== null;
                                  const hasProgress = progressText.trim().length > 0;
                                  const hasProof = proofText.trim().length > 0 &&
                                    (proofText.includes('Checked') || proofText.includes('not checked'));
                                  const hasAction = actionText.trim().length > 0 &&
                                    !actionText.includes('No lane action recorded');
                                  return cells.length >= 7 && hasStatus && hasProgress && hasProof && hasAction
                                    ? null
                                    : text.trim().replace(/\\s+/g, ' ').slice(0, 120);
                                })
                                .filter(Boolean)
                                .slice(0, 8)
                                """
                            )
                            result["v3_build_served"] = (
                                page.locator(
                                    f'html[data-ux-build="{EXPECTED_V3_BUILD}"]'
                                ).count()
                                > 0
                            )
                            result["v3_screen_class"] = (
                                page.locator('body.v3-app[class*="v3-screen-"]').count()
                                > 0
                            )
                            briefing = page.locator("[data-v3-universal-briefing]")
                            result["v3_universal_briefing"] = briefing.count() > 0
                            result["v3_briefing_visible"] = (
                                not _route_requires_v3_briefing(route)
                                or (
                                    bool(result["v3_universal_briefing"])
                                    and briefing.is_visible()
                                )
                            )
                            result["v3_briefing_text"] = (
                                briefing.inner_text(timeout=BODY_TIMEOUT_MS)
                                if bool(result["v3_universal_briefing"])
                                else ""
                            )
                            page.screenshot(
                                path=str(output_dir / f"{viewport_name}-{name}.png"),
                                full_page=False,
                            )
                        except PlaywrightError as exc:
                            result["page_error"] = _error_summary(exc)
                        results.append(result)
                    finally:
                        page.close()
        finally:
            browser.close()

    failures = [row for row in results if result_failed(row)]
    for row in results:
        print(row)
    print(f"screenshot_dir={output_dir}")
    print(f"failure_count={len(failures)}")
    return 1 if failures else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Browser QA for live dashboard data and health panels.",
    )
    parser.add_argument(
        "--readiness-scope",
        choices=(FULL_READINESS_SCOPE, REVIEW_SUBSET_READINESS_SCOPE),
        default=FULL_READINESS_SCOPE,
        help=(
            "full requires full-universe tradable readiness; review-subset accepts "
            "semi-automatic review mode with zero hard blockers."
        ),
    )
    return parser.parse_args()


def _empty_result(viewport: str, route: str) -> dict[str, object]:
    return {
        "viewport": viewport,
        "route": route,
        "page_error": "",
        "forbidden_hits": [],
        "horizontal_overflow": False,
        "clipped_controls": [],
        "health_visible": False,
        "health_panel_count": 0,
        "health_rows_count": 0,
        "health_rows_missing_fields": [],
        "cockpit_data_state_visible": False,
        "cockpit_lane_rows_count": 0,
        "cockpit_lane_rows_missing_fields": [],
        "operational_readiness_failures": [],
        "v3_build_served": False,
        "v3_screen_class": False,
        "v3_universal_briefing": False,
        "v3_briefing_visible": False,
        "v3_briefing_text": "",
    }


def _error_summary(exc: PlaywrightError) -> str:
    return f"{exc.__class__.__name__}: {str(exc).splitlines()[0]}"


def _load_page_body(page: Any, url: str) -> str:
    last_error: PlaywrightError | None = None
    for attempt in range(PAGE_LOAD_ATTEMPTS):
        try:
            page.goto(
                url,
                wait_until=PAGE_LOAD_STATE,
                timeout=PAGE_LOAD_TIMEOUT_MS,
            )
            body = page.locator("body")
            body.wait_for(state="visible", timeout=BODY_TIMEOUT_MS)
            return str(body.inner_text(timeout=BODY_TIMEOUT_MS))
        except PlaywrightError as exc:
            last_error = exc
            if attempt < PAGE_LOAD_ATTEMPTS - 1:
                page.wait_for_timeout(PAGE_RETRY_DELAY_MS)
                continue
    if last_error is None:
        raise RuntimeError("page load failed without Playwright error")
    raise last_error


def result_failed(row: Mapping[str, object]) -> bool:
    return (
        bool(row["page_error"])
        or bool(row["forbidden_hits"])
        or bool(row["horizontal_overflow"])
        or bool(row["clipped_controls"])
        or not _has_valid_health_proof(row)
        or bool(row["health_rows_missing_fields"])
        or bool(row.get("cockpit_lane_rows_missing_fields"))
        or bool(row["operational_readiness_failures"])
        or not bool(row["v3_build_served"])
        or not bool(row["v3_screen_class"])
        or not bool(row["v3_universal_briefing"])
        or _has_default_briefing_copy(row)
        or (
            _route_requires_v3_briefing(str(row["route"]))
            and not bool(row["v3_briefing_visible"])
        )
    )


def _has_valid_health_proof(row: Mapping[str, object]) -> bool:
    if bool(row["health_visible"]) and int(row["health_rows_count"]) > 0:
        return True
    return (
        str(row["route"]) in COCKPIT_ROUTES
        and bool(row.get("cockpit_data_state_visible"))
        and int(row.get("cockpit_lane_rows_count") or 0) > 0
    )


def _route_requires_v3_briefing(route: str) -> bool:
    return route not in COCKPIT_ROUTES


def _has_default_briefing_copy(row: Mapping[str, object]) -> bool:
    if not _route_requires_v3_briefing(str(row["route"])):
        return False
    text = str(row.get("v3_briefing_text") or "")
    return any(snippet in text for snippet in DEFAULT_BRIEFING_SNIPPETS)


def _forbidden_term_hits(text: str) -> list[str]:
    lower_text = text.lower()
    return [
        term
        for term, pattern in _FORBIDDEN_TERM_PATTERNS
        if pattern.search(lower_text)
    ]


def _operational_readiness_failures(
    base_url: str,
    *,
    readiness_scope: str = FULL_READINESS_SCOPE,
) -> list[str]:
    failures: list[str] = []
    full_live = _json_get(f"{base_url}/status/full-live-readiness")
    data_load = _json_get(f"{base_url}/status/data-load")
    data_sources = _json_get(f"{base_url}/status/data-sources")
    if not full_live:
        failures.append("/status/full-live-readiness unavailable")
    elif readiness_scope == REVIEW_SUBSET_READINESS_SCOPE:
        if full_live.get("review_operational_ready") is not True:
            failures.append(
                f"full-live review_operational_ready={full_live.get('review_operational_ready')!r}"
            )
        if _int_value(full_live.get("blocker_count")) > 0:
            failures.append(f"full-live blocker_count={full_live.get('blocker_count')!r}")
        if str(full_live.get("verdict") or "") not in {
            "ready_for_full_live_cycle",
            "ready_with_partial_lanes",
        }:
            failures.append(f"full-live verdict={full_live.get('verdict')!r}")
    else:
        if full_live.get("ready") is not True:
            failures.append(f"full-live ready={full_live.get('ready')!r}")
        if full_live.get("tradable_ready") is not True:
            failures.append(f"full-live tradable_ready={full_live.get('tradable_ready')!r}")
        if str(full_live.get("verdict") or "") != "ready_for_full_live_cycle":
            failures.append(f"full-live verdict={full_live.get('verdict')!r}")
    if not data_load:
        failures.append("/status/data-load unavailable")
    elif readiness_scope == REVIEW_SUBSET_READINESS_SCOPE:
        if data_load.get("ready") is not True:
            failures.append(f"data-load ready={data_load.get('ready')!r}")
        if data_load.get("review_operational_ready") is not True:
            failures.append(
                f"data-load review_operational_ready={data_load.get('review_operational_ready')!r}"
            )
        if _int_value(data_load.get("blocker_count")) > 0:
            failures.append(f"data-load blocker_count={data_load.get('blocker_count')!r}")
    elif (
        str(data_load.get("status_class") or "") != "pass"
        and not _data_load_has_only_context_warnings(data_load)
    ):
        failures.append(f"data-load status_class={data_load.get('status_class')!r}")
    if isinstance(data_load, Mapping):
        health = data_load.get("health_monitor")
        if isinstance(health, Mapping):
            health_state = str(health.get("status") or "").lower()
            if health_state in {"stale", "unavailable"}:
                failures.append(f"health-monitor status={health_state!r}")
            if health.get("reliable") is False:
                failures.append("health-monitor reliable=false")
    if not data_sources:
        failures.append("/status/data-sources unavailable")
    else:
        text = json.dumps(data_sources).lower()
        for token in ("fallback", "demo", "mock", "fake", "fixture", "monkey"):
            if token in text:
                failures.append(f"data-sources contains forbidden token {token!r}")
                break
    failures.extend(_operational_payload_failures(base_url))
    return failures


def _operational_payload_failures(base_url: str) -> list[str]:
    failures: list[str] = []
    for path in OPERATIONAL_PAYLOAD_ENDPOINTS:
        payload = _json_get(f"{base_url}{path}")
        if payload == {}:
            failures.append(f"{path} unavailable")
            continue
        token = _first_operational_payload_forbidden_token(payload)
        if token:
            failures.append(f"{path} contains non-operational token {token!r}")
    return failures


def _first_operational_payload_forbidden_token(payload: object) -> str | None:
    if isinstance(payload, Mapping):
        for value in payload.values():
            token = _first_operational_payload_forbidden_token(value)
            if token:
                return token
        return None
    if isinstance(payload, list | tuple | set):
        for value in payload:
            token = _first_operational_payload_forbidden_token(value)
            if token:
                return token
        return None
    text = str(payload or "")
    for token, pattern in _OPERATIONAL_PAYLOAD_PATTERNS:
        if pattern.search(text):
            return token
    return None


def _json_get(url: str) -> Any:
    for attempt in range(JSON_GET_ATTEMPTS):
        try:
            with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, (dict, list)) else {}
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            if attempt < JSON_GET_ATTEMPTS - 1:
                import time

                time.sleep(JSON_RETRY_DELAY_SECONDS)
                continue
            return {}
    return {}


def _data_load_has_only_context_warnings(data_load: Mapping[str, object]) -> bool:
    if data_load.get("tradable_ready") is not True:
        return False
    warnings = data_load.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        return False
    return all(_data_load_warning_is_nonblocking(row, data_load) for row in warnings)


def _data_load_warning_is_nonblocking(
    row: object,
    data_load: Mapping[str, object],
) -> bool:
    return _data_load_warning_is_context(row) or _data_load_warning_is_trade_progress(
        row,
        data_load,
    )


def _data_load_warning_is_context(row: object) -> bool:
    if not isinstance(row, Mapping):
        return False
    return (
        str(row.get("kind") or "") in CONTEXT_DATA_WARNING_KINDS
        and str(row.get("item") or "") in CONTEXT_DATA_WARNING_ITEMS
    )


def _data_load_warning_is_trade_progress(
    row: object,
    data_load: Mapping[str, object],
) -> bool:
    if not isinstance(row, Mapping):
        return False
    if str(row.get("kind") or "") != "data_refresh":
        return False
    if str(row.get("item") or "") != "stock_trades":
        return False
    market_flow = data_load.get("market_flow_summary")
    if not isinstance(market_flow, Mapping):
        return False
    expected = _int_value(market_flow.get("expected_ticker_count"))
    usable = _int_value(market_flow.get("usable_ticker_count"))
    signals = _int_value(market_flow.get("signal_ticker_count"))
    return (
        str(market_flow.get("status") or "") == "ready"
        and expected > 0
        and usable >= expected
        and signals >= expected
    )


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
