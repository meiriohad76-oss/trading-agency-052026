from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from dotenv import load_dotenv

PASS = "PASS"
WARN = "WARN"
BLOCK = "BLOCK"


def load_key_statuses(
    live_config: Mapping[str, object],
) -> list[dict[str, object]]:
    load_dotenv()
    provider = str(live_config.get("provider", "")).lower()
    keys = [
        _key("ALPACA_API_KEY", ".env", "Alpaca market-data access", provider == "alpaca"),
        _key("ALPACA_SECRET_KEY", ".env", "Alpaca market-data access", provider == "alpaca"),
        _sec_user_agent_key(live_config),
        _key("OPENAI_API_KEY", ".env", "Future LLM review calls", required=False),
    ]
    if provider == "massive":
        keys.append(
            _any_key(
                ("MASSIVE_API_KEY", "POLYGON_API_KEY"),
                ".env",
                "Massive/Polygon market-flow access",
                required=True,
            )
        )
    return keys


def _key(
    name: str,
    file_path: str,
    purpose: str,
    required: bool,
) -> dict[str, object]:
    present = os.environ.get(name, "").strip() != ""
    status = PASS if present else (BLOCK if required else WARN)
    return {
        "name": name,
        "required": required,
        "present": present,
        "status": status,
        "file": file_path,
        "purpose": purpose,
    }


def _any_key(
    names: tuple[str, ...],
    file_path: str,
    purpose: str,
    required: bool,
) -> dict[str, object]:
    present = any(os.environ.get(name, "").strip() != "" for name in names)
    status = PASS if present else (BLOCK if required else WARN)
    return {
        "name": " or ".join(names),
        "required": required,
        "present": present,
        "status": status,
        "file": file_path,
        "purpose": purpose,
    }


def _sec_user_agent_key(live_config: Mapping[str, object]) -> dict[str, object]:
    checks = _sequence_field(live_config, "checks")
    config_passed = any(
        _mapping(item).get("label") == "SEC User-Agent"
        and _mapping(item).get("status") == PASS
        for item in checks
    )
    present = os.environ.get("SEC_USER_AGENT", "").strip() != "" or config_passed
    return {
        "name": "SEC_USER_AGENT",
        "required": True,
        "present": present,
        "status": PASS if present else BLOCK,
        "file": ".env or research/config/live-refresh.local.json",
        "purpose": "Required contact string for SEC EDGAR requests",
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence_field(payload: Mapping[str, object], key: str) -> Sequence[object]:
    value = payload.get(key)
    return value if isinstance(value, list) else []
