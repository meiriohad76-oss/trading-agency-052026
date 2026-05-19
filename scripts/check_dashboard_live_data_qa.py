from __future__ import annotations

import json
import re
from urllib.error import URLError
from urllib.request import urlopen
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


PAGES = (
    "/",
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
    "demo",
    "mock",
    "fake",
    "fixture",
    "monkey",
)
VIEWPORTS = (
    ("desktop", {"width": 1440, "height": 1100}),
    ("mobile", {"width": 390, "height": 900}),
)
PAGE_LOAD_STATE = "domcontentloaded"
PAGE_LOAD_TIMEOUT_MS = 30_000
BODY_TIMEOUT_MS = 10_000
BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = 10
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
    "runtime_artifact_fallback",
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
    output_dir = Path("research/results/latest-ui-live-data-qa")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    operational_readiness_failures = _operational_readiness_failures(BASE_URL)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for viewport_name, viewport in VIEWPORTS:
                page = browser.new_page(viewport=viewport)
                try:
                    for route in PAGES:
                        name = (route.strip("/") or "command").replace("/", "-")
                        result = _empty_result(viewport_name, route)
                        result["operational_readiness_failures"] = list(
                            operational_readiness_failures
                        )
                        try:
                            page.goto(
                                f"{BASE_URL}{route}",
                                wait_until=PAGE_LOAD_STATE,
                                timeout=PAGE_LOAD_TIMEOUT_MS,
                            )
                            page.locator("body").wait_for(
                                state="visible",
                                timeout=BODY_TIMEOUT_MS,
                            )
                            body = page.locator("body").inner_text(timeout=BODY_TIMEOUT_MS)
                            lower_body = body.lower()
                            result["forbidden_hits"] = [
                                term
                                for term in FORBIDDEN_TERMS
                                if term.lower() in lower_body
                            ]
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
        "operational_readiness_failures": [],
    }


def _error_summary(exc: PlaywrightError) -> str:
    return f"{exc.__class__.__name__}: {str(exc).splitlines()[0]}"


def result_failed(row: Mapping[str, object]) -> bool:
    return (
        bool(row["page_error"])
        or bool(row["forbidden_hits"])
        or bool(row["horizontal_overflow"])
        or bool(row["clipped_controls"])
        or not bool(row["health_visible"])
        or int(row["health_rows_count"]) <= 0
        or bool(row["health_rows_missing_fields"])
        or bool(row["operational_readiness_failures"])
    )


def _operational_readiness_failures(base_url: str) -> list[str]:
    failures: list[str] = []
    full_live = _json_get(f"{base_url}/status/full-live-readiness")
    data_load = _json_get(f"{base_url}/status/data-load")
    data_sources = _json_get(f"{base_url}/status/data-sources")
    if not full_live:
        failures.append("/status/full-live-readiness unavailable")
    else:
        if full_live.get("ready") is not True:
            failures.append(f"full-live ready={full_live.get('ready')!r}")
        if full_live.get("tradable_ready") is not True:
            failures.append(f"full-live tradable_ready={full_live.get('tradable_ready')!r}")
        if str(full_live.get("verdict") or "") != "ready_for_full_live_cycle":
            failures.append(f"full-live verdict={full_live.get('verdict')!r}")
    if not data_load:
        failures.append("/status/data-load unavailable")
    else:
        if (
            str(data_load.get("status_class") or "") != "pass"
            and not _data_load_has_only_context_warnings(data_load)
        ):
            failures.append(f"data-load status_class={data_load.get('status_class')!r}")
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
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, (dict, list)) else {}


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
