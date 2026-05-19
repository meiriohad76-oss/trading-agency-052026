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
    summary = check_paper_review_status(
        base_url=args.base_url,
        min_queue=args.min_queue,
        min_reviewed=args.min_reviewed,
        max_pending=args.max_pending,
    )
    print(json.dumps(summary, sort_keys=True))


def check_paper_review_status(
    *,
    base_url: str = DEFAULT_BASE_URL,
    min_queue: int = 0,
    min_reviewed: int = 0,
    max_pending: int | None = None,
) -> dict[str, object]:
    payload = _mapping(_fetch_json(base_url, "/status/paper-review"))
    progress = _mapping(payload["progress"])
    queue = payload["queue"]
    if not isinstance(queue, list):
        raise TypeError("paper review queue must be a list")
    total_count = _int_value(progress, "total_count")
    reviewed_count = _int_value(progress, "reviewed_count")
    pending_count = _int_value(progress, "pending_count")
    if total_count < min_queue:
        raise RuntimeError("paper review queue count is below the required minimum")
    if reviewed_count < min_reviewed:
        raise RuntimeError("paper review reviewed count is below the required minimum")
    if max_pending is not None and pending_count > max_pending:
        raise RuntimeError("paper review pending count is above the allowed maximum")
    return {
        "cycle_id": payload["cycle_id"],
        "verdict": payload["verdict"],
        "total_count": total_count,
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
        "approve_count": _int_value(progress, "approve_count"),
        "defer_count": _int_value(progress, "defer_count"),
        "reject_count": _int_value(progress, "reject_count"),
    }


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
    parser = argparse.ArgumentParser(description="Smoke-check paper review status.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-queue", type=int, default=0)
    parser.add_argument("--min-reviewed", type=int, default=0)
    parser.add_argument("--max-pending", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    main()
