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
    summary = check_provider_readiness(
        base_url=args.base_url,
        require_configured=args.require_configured,
    )
    print(json.dumps(summary, sort_keys=True))


def check_provider_readiness(
    *,
    base_url: str = DEFAULT_BASE_URL,
    require_configured: str = "",
) -> dict[str, object]:
    payload = _mapping(_fetch_json(base_url, "/status/provider-readiness"))
    providers = _provider_index(payload)
    missing_required = [
        label
        for label in _requested_labels(require_configured)
        if providers.get(label, {}).get("configured") is not True
    ]
    if payload.get("ready") is not True:
        raise RuntimeError("provider readiness is missing required active keys")
    if missing_required:
        raise RuntimeError(f"provider keys are missing: {', '.join(missing_required)}")
    return {
        "ready": payload["ready"],
        "state": payload["state"],
        "provider_count": _int_value(payload, "provider_count"),
        "configured_count": _int_value(payload, "configured_count"),
        "active_required_count": _int_value(payload, "active_required_count"),
        "blocker_count": _int_value(payload, "blocker_count"),
        "warning_count": _int_value(payload, "warning_count"),
    }


def _provider_index(payload: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    value = payload.get("providers")
    if not isinstance(value, list):
        raise TypeError("providers must be a list")
    return {
        str(provider["label"]).lower(): provider
        for provider in value
        if isinstance(provider, Mapping)
    }


def _requested_labels(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


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
    parser = argparse.ArgumentParser(description="Smoke-check provider key readiness.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--require-configured",
        default="",
        help="Comma-separated provider labels that must be configured.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
