from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
HTTP_OK = 200


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
) -> dict[str, object]:
    health = _fetch_json(base_url, "/health")
    reports = _fetch_json(base_url, "/reports/selection")
    decisions = _fetch_json(base_url, "/risk/decisions")
    metrics = _fetch_text(base_url, "/metrics")
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
        "source_health": metric_value(metrics, "agency_source_health_total"),
    }


def metric_value(metrics: str, name: str) -> float:
    for line in metrics.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split(maxsplit=1)[1])
    raise KeyError(name)


def _fetch_json(base_url: str, path: str) -> Any:
    text = _fetch_text(base_url, path)
    return json.loads(text)


def _fetch_text(base_url: str, path: str) -> str:
    try:
        with urlopen(f"{base_url}{path}", timeout=10) as response:
            if response.status != HTTP_OK:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            text: str = response.read().decode("utf-8")
            return text
    except URLError as exc:
        raise RuntimeError(f"{path} is unavailable") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check the local FastAPI runtime.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-selection-reports", type=int, default=0)
    parser.add_argument("--min-risk-decisions", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
