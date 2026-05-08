from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def structured_log(
    event: str,
    *,
    level: str = "INFO",
    timestamp: datetime | None = None,
    **fields: object,
) -> str:
    """Render one compact JSON log line for scripts and runtime jobs."""
    payload: dict[str, Any] = {
        "event": event,
        "level": level.upper(),
        "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        **fields,
    }
    return json.dumps(payload, sort_keys=True)
