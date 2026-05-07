from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from agency.contracts import validate_contract

DEFAULT_REQUIRED_SAMPLE_COUNT = 50


def build_learning_outcome(
    outcomes: Sequence[Mapping[str, object]] | None = None,
    *,
    generated_at: str | None = None,
    required_sample_count: int = DEFAULT_REQUIRED_SAMPLE_COUNT,
) -> dict[str, object]:
    """Build a conservative learning snapshot from closed paper outcomes."""
    sample_count = len(outcomes or [])
    status = "READY" if sample_count >= required_sample_count else "PREMATURE"
    snapshot: dict[str, object] = {
        "schema_version": "0.1.0",
        "generated_at": generated_at or _now_utc(),
        "status": status,
        "sample_count": sample_count,
        "required_sample_count": required_sample_count,
        "message": _message(status, sample_count, required_sample_count),
        "requirements": _requirements(sample_count, required_sample_count),
    }
    validate_contract("learning-outcome", snapshot)
    return snapshot


def _requirements(sample_count: int, required_sample_count: int) -> list[dict[str, str]]:
    sample_status = "PASS" if sample_count >= required_sample_count else "WARN"
    return [
        {
            "name": "closed_trade_samples",
            "status": sample_status,
            "reason": f"{sample_count} of {required_sample_count} required samples",
        },
        {
            "name": "backtest_validation",
            "status": "WARN",
            "reason": "research validation is still the authority for threshold changes",
        },
        {
            "name": "audit_persistence",
            "status": "WARN",
            "reason": "learning changes are not persisted or applied automatically",
        },
    ]


def _message(status: str, sample_count: int, required_sample_count: int) -> str:
    if status == "READY":
        return "Learning sample size is ready for review; automatic tuning remains disabled."
    return f"Sample size {sample_count} is below the {required_sample_count} outcome threshold."


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
