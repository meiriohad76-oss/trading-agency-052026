from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
HTTP_OK = 200


def main() -> None:
    args = _parse_args()
    summary = check_operational_readiness(
        base_url=args.base_url,
        min_queue=args.min_queue,
        min_reviewed=args.min_reviewed,
        fail_on_warning=args.fail_on_warning,
    )
    print(json.dumps(summary, sort_keys=True))


def check_operational_readiness(
    *,
    base_url: str = DEFAULT_BASE_URL,
    min_queue: int = 1,
    min_reviewed: int = 0,
    fail_on_warning: bool = False,
) -> dict[str, object]:
    payload = _mapping(_fetch_json(base_url, "/status/operational-readiness"))
    progress = _mapping(_mapping(payload["paper_review"])["progress"])
    total_count = _int_value(progress, "total_count")
    reviewed_count = _int_value(progress, "reviewed_count")
    if payload.get("ready") is not True:
        raise RuntimeError(_failure_detail(payload, "operational readiness is blocked"))
    if total_count < min_queue:
        raise RuntimeError("paper review queue count is below the required minimum")
    if reviewed_count < min_reviewed:
        raise RuntimeError("paper review reviewed count is below the required minimum")
    warning_count = _int_value(payload, "warning_count")
    if fail_on_warning and warning_count > 0:
        raise RuntimeError(_failure_detail(payload, "operational readiness has warnings"))
    return {
        "ready": payload["ready"],
        "state": payload["state"],
        "status_label": payload["status_label"],
        "blocker_count": _int_value(payload, "blocker_count"),
        "warning_count": warning_count,
        "cycle_id": _mapping(payload["live_readiness"]).get("cycle_id"),
        "queue_count": total_count,
        "reviewed_count": reviewed_count,
        "pending_count": _int_value(progress, "pending_count"),
    }


def _failure_detail(payload: Mapping[str, object], prefix: str) -> str:
    actions = payload.get("next_actions", [])
    if not isinstance(actions, list) or not actions:
        return prefix
    return f"{prefix}: {actions[0]}"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected a mapping")
    return value


def _int_value(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _fetch_json(base_url: str, path: str) -> Any:
    try:
        with urlopen(f"{base_url}{path}", timeout=10) as response:
            if response.status != HTTP_OK:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"{path} is unavailable") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check operational paper readiness.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-queue", type=int, default=1)
    parser.add_argument("--min-reviewed", type=int, default=0)
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
