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
HTTP_MAX_ATTEMPTS = 4


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
    full_live = _mapping(_fetch_json(base_url, "/status/full-live-readiness"))
    progress = _mapping(_mapping(payload["paper_review"])["progress"])
    data_refresh = _optional_mapping(payload.get("data_refresh"))
    data_load = _optional_mapping(payload.get("data_load_status"))
    live_readiness = _optional_mapping(payload.get("live_readiness"))
    total_count = _int_value(progress, "total_count")
    reviewed_count = _int_value(progress, "reviewed_count")
    runtime_cycle_id = _optional_text(live_readiness.get("cycle_id"))
    data_load_cycle_id = _optional_text(data_load.get("cycle_id"))
    if (
        runtime_cycle_id
        and data_load_cycle_id
        and runtime_cycle_id != data_load_cycle_id
    ):
        raise RuntimeError(
            "operational readiness cycle mismatch: "
            f"runtime={runtime_cycle_id}; data_load={data_load_cycle_id}"
        )
    if payload.get("ready") is not True:
        raise RuntimeError(_failure_detail(payload, "operational readiness is blocked"))
    if full_live.get("review_operational_ready") is not True:
        verdict = str(full_live.get("verdict", "unknown"))
        raise RuntimeError(
            _failure_detail(
                full_live,
                f"full-live readiness is not review-operational ({verdict})",
            )
        )
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
        "cycle_id": runtime_cycle_id or data_load_cycle_id,
        "full_live_verdict": full_live.get("verdict"),
        "full_live_state": full_live.get("state"),
        "full_live_status_label": full_live.get("status_label"),
        "review_operational_ready": full_live.get("review_operational_ready"),
        "tradable_ready": full_live.get("tradable_ready"),
        "data_refresh_state": data_refresh.get("state"),
        "data_refresh_status_label": data_refresh.get("status_label"),
        "data_refresh_eta": data_refresh.get("eta_label"),
        "data_load_state": data_load.get("state"),
        "data_load_status_label": data_load.get("status_label"),
        "data_load_as_of": data_load.get("as_of"),
        "data_load_checked_at": data_load.get("status_checked_at"),
        "queue_count": total_count,
        "reviewed_count": reviewed_count,
        "pending_count": _int_value(progress, "pending_count"),
    }


def _failure_detail(payload: Mapping[str, object], prefix: str) -> str:
    actions = payload.get("next_actions", [])
    if not isinstance(actions, list) or not actions:
        return prefix
    detail = "; ".join(str(action) for action in actions[:3])
    return f"{prefix}: {detail}"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected a mapping")
    return value


def _optional_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: object) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _int_value(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _fetch_json(base_url: str, path: str) -> Any:
    last_error: BaseException | None = None
    for attempt in range(HTTP_MAX_ATTEMPTS):
        try:
            request = Request(f"{base_url}{path}", headers={"Connection": "close"})
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                if response.status != HTTP_OK:
                    raise RuntimeError(f"{path} returned HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except (ConnectionResetError, TimeoutError, URLError) as exc:
            last_error = exc
            if attempt < HTTP_MAX_ATTEMPTS - 1:
                time.sleep(0.25 * (attempt + 1))
                continue
    raise RuntimeError(f"{path} is unavailable") from last_error


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check operational paper readiness.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-queue", type=int, default=1)
    parser.add_argument("--min-reviewed", type=int, default=0)
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
