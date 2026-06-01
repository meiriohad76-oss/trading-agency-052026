from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_URL = "http://127.0.0.1:8000/cockpit"
PREFLIGHT_ENDPOINTS = (
    "/status/data-load",
    "/status/full-live-readiness",
    "/status/data-sources",
    "/status/execution-preview",
)
PREFLIGHT_REPORT_NAME = "cockpit-preflight.json"
SCENARIOS = ("normal", "no-actionable", "outage", "submitted")
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
                    page = browser.new_page(
                        viewport=profile["viewport"],
                        has_touch=bool(profile.get("has_touch")),
                        is_mobile=bool(profile.get("is_mobile")),
                    )
                    page.on("console", _console_error_collector(console_errors))
                    page.on("pageerror", _page_error_collector(page_errors))
                    result = {
                        "viewport": viewport_name,
                        "url": target_url,
                        "scenario": scenario_name,
                        "focus": args.focus,
                        "http_ok": False,
                        "console_errors": console_errors,
                        "page_errors": page_errors,
                        "horizontal_overflow": False,
                        "bluf_visible": False,
                        "phase_visible": False,
                        "candidate_visible": False,
                        "submit_gate_safe": False,
                        "panel_screenshots": [],
                        "unreadable_controls": [],
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
                        page.wait_for_selector('[data-cockpit-cycle][data-cockpit-ready="true"]', timeout=10_000)
                        result["horizontal_overflow"] = bool(
                            page.evaluate(
                                "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                            )
                        )
                        result["bluf_visible"] = _is_in_first_viewport(page, ".cockpit-bluf")
                        result["phase_visible"] = page.locator(".cockpit-phase:not([hidden])").first.is_visible()
                        result["candidate_visible"] = page.locator(".cockpit-candidate-row, .empty-state").count() > 0
                        result["submit_gate_safe"] = _submit_gate_is_safe(page)
                        result["focus_errors"] = _exercise_focus(page, args.focus)
                        result["panel_screenshots"] = _screenshot_panels(
                            page,
                            output_dir,
                            f"{viewport_name}-{scenario_name}",
                        )
                        result["unreadable_controls"] = page.evaluate(
                            """
                            () => Array.from(document.querySelectorAll('button, a.button, .status-pill'))
                              .filter((el) => (
                                el.scrollWidth > el.clientWidth + 1 ||
                                el.scrollHeight > el.clientHeight + 1
                              ))
                              .map((el) => (el.textContent || '').trim().replace(/\\s+/g, ' '))
                              .filter(Boolean)
                              .slice(0, 10)
                            """
                        )
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
    failures = [result for result in results if _failed(result)]
    print(f"preflight={preflight_path}")
    print(f"report={report_path}")
    print(f"failure_count={len(failures)}")
    return 1 if failures else 0


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
    return urljoin(root, endpoint)


def _json_get(url: str) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                return {"available": False, "status_code": response.status}
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc)}
    if isinstance(payload, dict):
        payload.setdefault("available", True)
        return payload
    return {"available": True, "payload": payload}


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


def _console_error_collector(console_errors: list[str]):
    def collect(message: Any) -> None:
        if message.type == "error":
            console_errors.append(str(message.text))

    return collect


def _page_error_collector(page_errors: list[str]):
    def collect(exc: BaseException) -> None:
        page_errors.append(str(exc))

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


def _submit_gate_is_safe(page: Any) -> bool:
    clearance = page.locator('[data-cockpit-phase-target="clearance"]').first
    if clearance.count() > 0:
        clearance.click()
    scenario_state = (
        page.locator("[data-cockpit-cycle]").first.get_attribute("data-cockpit-scenario")
        or "normal"
    )
    safety_scenario = scenario_state in {"outage", "no-actionable", "submitted"}
    button = page.locator("[data-cockpit-submit-button]").first
    if button.count() == 0:
        return True
    initially_disabled = button.is_disabled()
    ack = page.locator("[data-cockpit-submit-ack]").first
    phrase = page.locator("[data-cockpit-submit-text]").first
    if ack.count() == 0 or phrase.count() == 0:
        return False
    ack.check()
    phrase.fill("wrong phrase")
    wrong_phrase_disabled = button.is_disabled()
    phrase.fill("submit paper orders")
    armed_enabled = not button.is_disabled()
    phrase.fill("")
    ack.uncheck()
    if safety_scenario:
        return initially_disabled and wrong_phrase_disabled and not armed_enabled
    return initially_disabled and wrong_phrase_disabled and armed_enabled


def _failed(result: dict[str, object]) -> bool:
    return (
        result.get("http_ok") is not True
        or bool(result.get("console_errors"))
        or bool(result.get("page_errors"))
        or result.get("horizontal_overflow") is True
        or result.get("bluf_visible") is not True
        or result.get("phase_visible") is not True
        or result.get("candidate_visible") is not True
        or result.get("submit_gate_safe") is not True
        or bool(result.get("focus_errors"))
        or bool(result.get("unreadable_controls"))
        or bool(result.get("error"))
    )


def _exercise_focus(page: Any, focus: str) -> list[str]:
    errors: list[str] = []
    if focus == "candidates":
        row_toggle = page.locator("[data-cockpit-row-toggle]").first
        if row_toggle.count() > 0:
            row_toggle.click()
            if not page.locator(".cockpit-row-detail").first.is_visible():
                errors.append("candidate row expansion did not open")
    elif focus == "portfolio":
        phase_button = page.locator('[data-cockpit-phase-target="portfolio"]')
        if phase_button.count() == 0 or not phase_button.first.is_visible():
            errors.append("portfolio phase target is missing or hidden")
            return errors
        phase_button.first.click()
        portfolio_phase = page.locator('[data-cockpit-phase="portfolio"]')
        if portfolio_phase.count() == 0:
            errors.append("portfolio phase panel is missing")
        elif not portfolio_phase.first.is_visible():
            errors.append("portfolio phase did not open")
    elif focus == "panels":
        for panel in PANEL_NAMES:
            page.locator(f'[data-cockpit-panel-target="{panel}"]').first.click()
            panel_locator = page.locator(f"#cockpit-panel-{panel}")
            if not panel_locator.is_visible():
                errors.append(f"{panel} panel did not open")
            panel_locator.locator("button[data-cockpit-panel-close]").first.click()
        candidates_phase = page.locator('[data-cockpit-phase-target="candidates"]').first
        if candidates_phase.count() > 0:
            candidates_phase.click()
        if page.locator("[data-cockpit-row-toggle]").first.count() > 0:
            page.locator("[data-cockpit-row-toggle]").first.click()
        detail_button = page.locator("[data-cockpit-ticker-detail]").first
        if detail_button.count() > 0:
            detail_button.click()
            if not page.locator("#cockpit-panel-ticker-detail").is_visible():
                errors.append("ticker detail panel did not open")
            page.locator("#cockpit-panel-ticker-detail button[data-cockpit-panel-close]").first.click()
    return errors


def _screenshot_panels(page: Any, output_dir: Path, viewport_name: str) -> list[str]:
    screenshots: list[str] = []
    for panel in PANEL_NAMES:
        trigger = page.locator(f'[data-cockpit-panel-target="{panel}"]').first
        if trigger.count() == 0:
            continue
        trigger.click()
        panel_locator = page.locator(f"#cockpit-panel-{panel}")
        if panel_locator.is_visible():
            path = output_dir / f"{viewport_name}-panel-{panel}.png"
            panel_locator.screenshot(path=str(path))
            screenshots.append(str(path))
        panel_locator.locator("button[data-cockpit-panel-close]").first.click()
    return screenshots


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


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
