from __future__ import annotations

import json
from pathlib import Path

from agency.views.candidates import candidate_local_llm_insight

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_local_llm_insight_reads_ticker_shadow_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "local-llm-insights.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "completed",
                "status_label": "Local LLM insights ready",
                "status_class": "pass",
                "model": "qwen2.5:7b",
                "mode": "shadow",
                "generated_at": "2026-05-28T10:00:00+00:00",
                "can_affect_trade_gates": False,
                "insights": [
                    {
                        "ticker": "MSFT",
                        "status": "completed",
                        "summary": "Evidence is constructive but needs volume follow-through.",
                        "bullish_case": ["Trend and flow agree"],
                        "bearish_case": ["Subscription context is mixed"],
                        "what_changed": ["Email evidence synced"],
                        "user_checks": ["Review order size"],
                        "contradictions": ["Bullish action with bearish context"],
                        "confidence": 0.67,
                        "can_affect_trade_gates": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    insight = candidate_local_llm_insight("msft", artifact_path=artifact)

    assert insight["available"] is True
    assert insight["status_label"] == "Local LLM insight ready"
    assert insight["model"] == "qwen2.5:7b"
    assert insight["summary"] == "Evidence is constructive but needs volume follow-through."
    assert insight["confidence_pct"] == 67
    assert insight["can_affect_trade_gates"] is False
    assert insight["trade_gate_note"] == "Advisory only; it cannot approve or block trades."
    assert insight["bullish_case"] == ["Trend and flow agree"]


def test_candidate_local_llm_insight_missing_ticker_is_not_available(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "local-llm-insights.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "completed",
                "status_label": "Local LLM insights ready",
                "status_class": "pass",
                "model": "qwen2.5:7b",
                "mode": "shadow",
                "can_affect_trade_gates": False,
                "insights": [{"ticker": "AAPL", "status": "completed"}],
            }
        ),
        encoding="utf-8",
    )

    insight = candidate_local_llm_insight("msft", artifact_path=artifact)

    assert insight["available"] is False
    assert insight["status"] == "not_run_for_ticker"
    assert insight["status_label"] == "Local LLM not run for MSFT"
    assert insight["can_affect_trade_gates"] is False


def test_candidate_local_llm_insight_failed_ticker_is_not_trade_evidence(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "local-llm-insights.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "completed",
                "status_label": "Local LLM insights ready",
                "status_class": "pass",
                "model": "qwen2.5:7b",
                "mode": "shadow",
                "can_affect_trade_gates": False,
                "insights": [
                    {
                        "ticker": "MSFT",
                        "status": "failed",
                        "summary": "Local LLM insight failed; use deterministic evidence only.",
                        "can_affect_trade_gates": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    insight = candidate_local_llm_insight("msft", artifact_path=artifact)

    assert insight["available"] is False
    assert insight["status_label"] == "Local LLM insight failed"
    assert insight["status_class"] == "warn"
    assert insight["can_affect_trade_gates"] is False


def test_candidate_local_llm_insight_invalid_artifact_is_unavailable(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "local-llm-insights.json"
    artifact.write_text("{not-json", encoding="utf-8")

    insight = candidate_local_llm_insight("MSFT", artifact_path=artifact)

    assert insight["available"] is False
    assert insight["status"] == "artifact_unreadable"
    assert insight["status_class"] == "warn"


def test_candidate_template_renders_local_llm_shadow_panel() -> None:
    template = (REPO_ROOT / "src/agency/templates/candidate_detail.html").read_text(
        encoding="utf-8"
    )

    assert "local_llm_insight" in template
    assert "Local Pi LLM Shadow Insight" in template
    assert "cannot approve or block trades" in template
