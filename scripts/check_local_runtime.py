from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
HTTP_OK = 200
SELECTION_REPORTS_ROUTE_BUDGET_SECONDS = 5.0
COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS = 12.0
HTTP_TIMEOUT_SECONDS = 30
HTTP_MAX_ATTEMPTS = 4
TimedFetchResult = Mapping[str, object]
TimedJsonFetcher = Callable[[str, str], TimedFetchResult]
TimedTextFetcher = Callable[[str, str], TimedFetchResult]
ROUTE_BUDGETS: dict[str, dict[str, object]] = {
    "/reports/selection": {
        "label": "Selection reports",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": SELECTION_REPORTS_ROUTE_BUDGET_SECONDS,
    },
    "/": {
        "label": "V3 cockpit root",
        "metric": "first_byte_seconds",
        "kind": "first-byte",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/cockpit": {
        "label": "V3 cockpit page",
        "metric": "first_byte_seconds",
        "kind": "first-byte",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/api/cockpit": {
        "label": "V3 cockpit API",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/command": {
        "label": "Command dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/final-selection": {
        "label": "Final selection dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/execution-preview": {
        "label": "Execution preview dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/signals": {
        "label": "Signals dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/portfolio-monitor": {
        "label": "Portfolio monitor dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/risk": {
        "label": "Risk dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/learning": {
        "label": "Learning dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/audit": {
        "label": "Audit dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
    "/market-regime": {
        "label": "Market regime dashboard",
        "metric": "total_seconds",
        "kind": "total",
        "seconds": COCKPIT_ROOT_FIRST_BYTE_BUDGET_SECONDS,
    },
}
DASHBOARD_TEXT_ROUTES = tuple(
    path
    for path in ROUTE_BUDGETS
    if path not in {"/reports/selection", "/api/cockpit"}
)


def main() -> None:
    args = _parse_args()
    summary = check_runtime(
        base_url=args.base_url,
        min_selection_reports=args.min_selection_reports,
        min_risk_decisions=args.min_risk_decisions,
    )
    print(json.dumps(summary, sort_keys=True))


def check_runtime(
    *,
    base_url: str = DEFAULT_BASE_URL,
    min_selection_reports: int = 0,
    min_risk_decisions: int = 0,
    timed_fetch_json: TimedJsonFetcher | None = None,
    timed_fetch_text: TimedTextFetcher | None = None,
) -> dict[str, object]:
    fetch_json = timed_fetch_json or _fetch_json_with_timing
    fetch_text = timed_fetch_text or _fetch_text_with_timing
    reports_probe_path = _selection_reports_probe_path(min_selection_reports)
    health_result = fetch_json(base_url, "/health")
    reports_result = fetch_json(base_url, reports_probe_path)
    decisions_result = fetch_json(base_url, "/risk/decisions")
    cockpit_api_result = fetch_json(base_url, "/api/cockpit")
    metrics_result = fetch_text(base_url, "/metrics")
    text_route_results = {
        path: fetch_text(base_url, path)
        for path in DASHBOARD_TEXT_ROUTES
    }
    route_timings = {
        "/health": _route_timing("/health", health_result),
        "/reports/selection": _route_timing("/reports/selection", reports_result),
        "/risk/decisions": _route_timing("/risk/decisions", decisions_result),
        "/api/cockpit": _route_timing("/api/cockpit", cockpit_api_result),
        "/metrics": _route_timing("/metrics", metrics_result),
        **{
            path: _route_timing(path, result)
            for path, result in text_route_results.items()
        },
    }
    _enforce_route_budgets(route_timings)
    health = _payload(health_result)
    reports = _payload(reports_result)
    decisions = _payload(decisions_result)
    metrics = _payload(metrics_result)
    if health.get("status") != "ok":
        raise RuntimeError("health endpoint did not report ok")
    if not isinstance(reports, list):
        raise TypeError("selection reports endpoint must return a list")
    if not isinstance(decisions, list):
        raise TypeError("risk decisions endpoint must return a list")
    if len(reports) < min_selection_reports:
        raise RuntimeError("selection report count is below the required minimum")
    if len(decisions) < min_risk_decisions:
        raise RuntimeError("risk decision count is below the required minimum")
    return {
        "health": health["status"],
        "selection_reports": len(reports),
        "risk_decisions": len(decisions),
        "source_health": metric_value(str(metrics), "agency_source_health_total"),
        "route_timings": route_timings,
    }


def _selection_reports_probe_path(min_selection_reports: int) -> str:
    limit = max(1, min_selection_reports)
    return f"/reports/selection?limit={limit}"


def metric_value(metrics: str, name: str) -> float:
    for line in metrics.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split(maxsplit=1)[1])
    raise KeyError(name)


def _fetch_json(base_url: str, path: str) -> Any:
    return _payload(_fetch_json_with_timing(base_url, path))


def _fetch_text(base_url: str, path: str) -> str:
    return str(_payload(_fetch_text_with_timing(base_url, path)))


def _fetch_json_with_timing(base_url: str, path: str) -> dict[str, object]:
    result = _fetch_text_with_timing(base_url, path)
    return {
        **result,
        "payload": json.loads(str(result["payload"])),
    }


def _fetch_text_with_timing(base_url: str, path: str) -> dict[str, object]:
    last_error: BaseException | None = None
    fetcher = _fetch_first_byte_with_timing if _is_first_byte_route(path) else _fetch_full_text_with_timing
    for attempt in range(HTTP_MAX_ATTEMPTS):
        try:
            return fetcher(base_url, path, attempt=attempt)
        except (ConnectionResetError, TimeoutError, httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if _is_timeout_error(exc):
                break
            if attempt < HTTP_MAX_ATTEMPTS - 1:
                time.sleep(0.25 * (attempt + 1))
                continue
    raise RuntimeError(f"{path} is unavailable") from last_error


def _fetch_full_text_with_timing(
    base_url: str,
    path: str,
    *,
    attempt: int,
) -> dict[str, object]:
    started = time.perf_counter()
    response = httpx.get(
        f"{base_url}{path}",
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    finished = time.perf_counter()
    if response.status_code != HTTP_OK:
        raise RuntimeError(f"{path} returned HTTP {response.status_code}")
    return {
        "path": path,
        "payload": response.text,
        "first_byte_seconds": round(response.elapsed.total_seconds(), 3),
        "total_seconds": round(finished - started, 3),
        "attempt": attempt + 1,
    }


def _fetch_first_byte_with_timing(
    base_url: str,
    path: str,
    *,
    attempt: int,
) -> dict[str, object]:
    started = time.perf_counter()
    with httpx.stream(
        "GET",
        f"{base_url}{path}",
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as response:
        first_byte_at = time.perf_counter()
        if response.status_code != HTTP_OK:
            raise RuntimeError(f"{path} returned HTTP {response.status_code}")
        payload = next(iter(response.iter_bytes(chunk_size=1)), b"").decode("utf-8")
        finished = time.perf_counter()
    return {
        "path": path,
        "payload": payload,
        "first_byte_seconds": round(first_byte_at - started, 3),
        "total_seconds": round(finished - started, 3),
        "attempt": attempt + 1,
    }


def _is_first_byte_route(path: str) -> bool:
    budget = ROUTE_BUDGETS.get(path)
    return bool(budget and budget.get("kind") == "first-byte")


def _is_timeout_error(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, httpx.TimeoutException))


def _payload(result: TimedFetchResult | Any) -> Any:
    if isinstance(result, Mapping) and "payload" in result:
        return result["payload"]
    return result


def _route_timing(path: str, result: TimedFetchResult) -> dict[str, object]:
    timing = {
        "first_byte_seconds": _float_value(result.get("first_byte_seconds")),
        "total_seconds": _float_value(result.get("total_seconds")),
    }
    budget = ROUTE_BUDGETS.get(path)
    if budget:
        timing["budget_seconds"] = budget["seconds"]
        timing["budget_metric"] = budget["metric"]
        timing["budget_status"] = (
            "pass" if float(timing[str(budget["metric"])]) <= float(budget["seconds"]) else "fail"
        )
    return timing


def _float_value(value: object) -> float:
    try:
        return round(float(value), 3)
    except TypeError, ValueError:
        return 0.0


def _enforce_route_budgets(
    route_timings: Mapping[str, Mapping[str, object]],
) -> None:
    for path, budget in ROUTE_BUDGETS.items():
        metric = str(budget["metric"])
        observed = float(route_timings.get(path, {}).get(metric, 0.0))
        maximum = float(budget["seconds"])
        if observed > maximum:
            label = str(budget["label"])
            kind = str(budget["kind"])
            raise RuntimeError(
                f"{label} route exceeded {maximum:.1f}s {kind} budget ({path}: {observed:.2f}s)"
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check the local FastAPI runtime.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-selection-reports", type=int, default=0)
    parser.add_argument("--min-risk-decisions", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
