from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
HTTP_OK = 200
HTTP_TIMEOUT_SECONDS = 60


def main() -> None:
    args = _parse_args()
    summary = check_paper_trade_path(
        base_url=args.base_url,
        min_orderable=args.min_orderable,
        min_submit_ready=args.min_submit_ready,
        min_order_approval_available=args.min_order_approval_available,
        require_submit_gate_open=args.require_submit_gate_open,
    )
    print(json.dumps(summary, sort_keys=True))


def check_paper_trade_path(
    *,
    base_url: str = DEFAULT_BASE_URL,
    min_orderable: int = 0,
    min_submit_ready: int = 0,
    min_order_approval_available: int = 0,
    require_submit_gate_open: bool = False,
) -> dict[str, object]:
    review = _mapping(_fetch_json(base_url, "/status/paper-review"))
    execution = _mapping(_fetch_json(base_url, "/status/execution-preview"))
    progress = _mapping(review["progress"])
    freshness = _mapping(execution.get("freshness_gate", {}))
    summary = {
        "cycle_id": execution.get("cycle_id") or review.get("cycle_id"),
        "paper_review_verdict": str(review.get("verdict") or ""),
        "review_total_count": _int_value(progress, "total_count"),
        "reviewed_count": _int_value(progress, "reviewed_count"),
        "pending_count": _int_value(progress, "pending_count"),
        "approve_count": _int_value(progress, "approve_count"),
        "ready": execution.get("ready") is True,
        "orderable_count": _int_value(execution, "ready_count"),
        "submit_ready_count": _int_value(execution, "submit_ready_count"),
        "order_approval_available_count": _int_value(
            execution,
            "order_approval_available_count",
        ),
        "review_only_count": _int_value(execution, "review_only_count"),
        "blocked_count": _int_value(execution, "blocked_count"),
        "disabled_count": _int_value(execution, "disabled_count"),
        "submit_gate_open": execution.get("submit_gate_open") is True,
        "freshness_ready": freshness.get("ready") is True,
    }
    failures = _paper_trade_path_failures(
        summary,
        execution=execution,
        min_orderable=min_orderable,
        min_submit_ready=min_submit_ready,
        min_order_approval_available=min_order_approval_available,
        require_submit_gate_open=require_submit_gate_open,
    )
    if failures:
        raise RuntimeError("; ".join(failures))
    return summary


def _paper_trade_path_failures(
    summary: Mapping[str, object],
    *,
    execution: Mapping[str, object],
    min_orderable: int,
    min_submit_ready: int,
    min_order_approval_available: int,
    require_submit_gate_open: bool,
) -> list[str]:
    failures: list[str] = []
    orderable = _int_value(summary, "orderable_count")
    submit_ready = _int_value(summary, "submit_ready_count")
    approval_available = _int_value(summary, "order_approval_available_count")
    if orderable < min_orderable:
        failures.append(
            f"orderable paper preview count is below required minimum "
            f"({orderable} < {min_orderable})"
        )
    if submit_ready < min_submit_ready:
        failures.append(
            f"submit-ready paper order count is below required minimum "
            f"({submit_ready} < {min_submit_ready})"
        )
    if approval_available < min_order_approval_available:
        failures.append(
            "order-approval-available count is below required minimum "
            f"({approval_available} < {min_order_approval_available})"
        )
    if require_submit_gate_open and summary.get("submit_gate_open") is not True:
        failures.append("paper submit gate is closed")
    if failures:
        blocker = _first_blocker(execution)
        if blocker:
            failures.append(f"first blocker: {blocker}")
    return failures


def _first_blocker(execution: Mapping[str, object]) -> str:
    blockers = execution.get("blockers", [])
    if not isinstance(blockers, list) or not blockers:
        return ""
    blocker = blockers[0]
    if not isinstance(blocker, Mapping):
        return ""
    ticker = str(blocker.get("ticker") or "unknown ticker")
    reason = str(blocker.get("reason") or "no reason supplied")
    return f"{ticker}: {reason}"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected a mapping")
    return value


def _int_value(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _fetch_json(base_url: str, path: str) -> Any:
    last_error: BaseException | None = None
    for attempt in range(2):
        try:
            request = Request(f"{base_url}{path}", headers={"Connection": "close"})
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                if response.status != HTTP_OK:
                    raise RuntimeError(f"{path} returned HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except (ConnectionResetError, TimeoutError, URLError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.25)
                continue
    raise RuntimeError(f"{path} is unavailable") from last_error


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-check the real paper-trade path from review to orderability.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-orderable", type=int, default=0)
    parser.add_argument("--min-submit-ready", type=int, default=0)
    parser.add_argument("--min-order-approval-available", type=int, default=0)
    parser.add_argument("--require-submit-gate-open", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
