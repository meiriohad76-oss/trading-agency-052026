from __future__ import annotations

import re
from collections.abc import Mapping

NON_OPERATIONAL_TOKENS = ("demo", "mock", "fake", "fixture", "manual-smoke")
_NON_OPERATIONAL_PATTERNS = tuple(
    re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", re.IGNORECASE)
    for token in NON_OPERATIONAL_TOKENS
)


def is_non_operational_payload(payload: Mapping[str, object]) -> bool:
    """Return True for local demo/test payloads that must not feed live dashboards."""
    fields = (
        payload.get("cycle_id"),
        payload.get("source"),
        payload.get("source_id"),
        payload.get("run_id"),
        payload.get("notes"),
        payload.get("detail"),
        payload.get("reason"),
    )
    return any(_contains_non_operational_token(field) for field in fields)


def _contains_non_operational_token(value: object) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(_contains_non_operational_token(item) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_non_operational_token(item) for item in value.values())
    text = str(value or "").casefold()
    return any(pattern.search(text) for pattern in _NON_OPERATIONAL_PATTERNS)
