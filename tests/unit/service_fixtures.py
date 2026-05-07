from __future__ import annotations

from agency.services import build_evidence_pack, build_final_selection, build_signal_result


def selection_report(
    *,
    action: str = "WATCH",
    score: float = 0.7,
    policy_status: str = "PASS",
    policy_reason: str = "confirmed evidence present",
    risk_flags: list[str] | None = None,
) -> dict[str, object]:
    report = build_final_selection(evidence_pack(score=score)).selection_report
    report["final_action"] = action
    report["final_conviction"] = abs(score)
    report["policy_gates"] = [
        {"name": "evidence_breadth", "status": policy_status, "reason": policy_reason}
    ]
    report["risk_flags"] = list(risk_flags or [])
    return report


def evidence_pack(score: float = 0.7) -> dict[str, object]:
    return build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[
            build_signal_result(
                cycle_id="cycle-1",
                ticker="AAPL",
                as_of="2026-05-07T09:30:00Z",
                lane="fundamentals",
                score=score,
                provenance=provenance(),
                confidence=0.9,
            )
        ],
    )


def source_health(
    *,
    status: str = "HEALTHY",
    freshness: str = "FRESH",
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "status": status,
        "checked_at": "2026-05-07T09:30:00Z",
        "freshness": freshness,
        "last_success_at": "2026-05-07T09:29:00Z",
        "observed_lag_seconds": 60,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": [],
    }


def provenance() -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": "CIK0000320193",
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
