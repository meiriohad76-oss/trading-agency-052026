from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEFAULT_URL = "http://127.0.0.1:8000/cockpit"
VIEWPORTS = (
    ("desktop-1920", {"width": 1920, "height": 1080}),
    ("desktop-1366", {"width": 1366, "height": 768}),
)


def main() -> int:
    args = _parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for viewport_name, viewport in VIEWPORTS:
                console_errors: list[str] = []
                page = browser.new_page(viewport=viewport)
                page.on("console", _console_error_collector(console_errors))
                result = {
                    "viewport": viewport_name,
                    "url": args.url,
                    "scenario": args.scenario,
                    "focus": args.focus,
                    "http_ok": False,
                    "console_errors": console_errors,
                    "horizontal_overflow": False,
                    "bluf_visible": False,
                    "phase_visible": False,
                    "candidate_visible": False,
                    "unreadable_controls": [],
                    "screenshot": "",
                    "error": "",
                }
                try:
                    response = page.goto(args.url, wait_until="networkidle", timeout=30_000)
                    result["http_ok"] = response is not None and response.status == 200
                    page.wait_for_selector(".cockpit-bluf", timeout=10_000)
                    result["horizontal_overflow"] = bool(
                        page.evaluate(
                            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                        )
                    )
                    result["bluf_visible"] = _is_in_first_viewport(page, ".cockpit-bluf")
                    result["phase_visible"] = _is_in_first_viewport(page, ".cockpit-phase")
                    result["candidate_visible"] = page.locator(".cockpit-candidate-row, .empty-state").count() > 0
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
                    screenshot_path = output_dir / f"{viewport_name}-{args.scenario}-{args.focus}.png"
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
    print(f"report={report_path}")
    print(f"failure_count={len(failures)}")
    return 1 if failures else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser QA for the V3 cockpit UX.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--focus", default="shell")
    parser.add_argument(
        "--output",
        default="research/results/ux-redesign-v3-qa/latest",
    )
    return parser.parse_args()


def _console_error_collector(console_errors: list[str]):
    def collect(message: Any) -> None:
        if message.type == "error":
            console_errors.append(str(message.text))

    return collect


def _is_in_first_viewport(page: Any, selector: str) -> bool:
    return bool(
        page.locator(selector).evaluate(
            """
            (el) => {
              const rect = el.getBoundingClientRect();
              return rect.top >= 0 && rect.top < window.innerHeight && rect.bottom > 0;
            }
            """
        )
    )


def _failed(result: dict[str, object]) -> bool:
    return (
        result.get("http_ok") is not True
        or bool(result.get("console_errors"))
        or result.get("horizontal_overflow") is True
        or result.get("bluf_visible") is not True
        or result.get("phase_visible") is not True
        or result.get("candidate_visible") is not True
        or bool(result.get("unreadable_controls"))
        or bool(result.get("error"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
