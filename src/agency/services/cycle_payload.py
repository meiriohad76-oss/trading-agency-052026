from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from agency.services.cycle import RuntimeCycleResult, build_runtime_cycle
from agency.services.risk import PortfolioPolicy


def build_runtime_cycle_from_payload(
    payload: Mapping[str, object],
    *,
    policy: PortfolioPolicy | None = None,
) -> RuntimeCycleResult:
    """Build a runtime cycle from a JSON-compatible command payload."""
    return build_runtime_cycle(
        cycle_id=str(payload["cycle_id"]),
        as_of=str(payload["as_of"]),
        generated_at=str(payload["generated_at"]),
        source_health=_mapping_sequence(payload.get("source_health", []), "source_health"),
        signals=_mapping_sequence(payload.get("signals", []), "signals"),
        tickers=_string_sequence(payload.get("tickers", []), "tickers"),
        policy=policy,
        current_gross_exposure_pct=_optional_float(
            payload.get("current_gross_exposure_pct"),
            default=0.0,
        ),
    )


def _mapping_sequence(value: object, field_name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    items: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{field_name} entries must be objects")
        items.append(cast(Mapping[str, object], item))
    return items


def _string_sequence(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    return [str(item).upper() for item in value]


def _optional_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    if not isinstance(value, int | float):
        raise TypeError("current_gross_exposure_pct must be numeric")
    return float(value)
