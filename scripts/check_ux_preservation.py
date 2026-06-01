from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "research" / "results" / "ux-preservation" / "latest"
DEFAULT_AUDIT_PATH = PROJECT_ROOT / "docs" / "audits" / "ux-preservation-uxc-014-2026-06-01.md"

PYTEST_GROUPS: dict[str, tuple[str, ...]] = {
    "signals": (
        "tests/unit/test_signal_evidence.py",
        "tests/unit/test_signal_evidence_fundamentals.py",
        "tests/unit/test_market_flow_signals.py",
        "tests/unit/test_signal_calibration.py",
        "tests/unit/test_signal_adapters.py",
    ),
    "fundamentals": (
        "tests/unit/test_signal_evidence_fundamentals.py",
        "tests/unit/test_fundamentals_signal.py",
        "tests/unit/test_fundamentals_growth.py",
        "tests/unit/test_forward_fundamentals_state.py",
        "tests/unit/test_sec_views_period_fix.py",
        "tests/unit/test_pit_loader.py",
    ),
    "subscription": (
        "tests/unit/test_subscription_thesis_signal.py",
        "tests/unit/test_subscription_email_agents.py",
        "tests/unit/test_portfolio_news_agent_bridge.py",
        "tests/unit/test_news_signal.py",
        "tests/unit/test_news_ticker_resolution.py",
        "tests/unit/test_fastapi_app.py::test_data_load_status_view_exposes_subscription_email_progress",
        "tests/unit/test_fastapi_app.py::test_candidate_email_evidence_ties_articles_to_current_judgement",
        "tests/unit/test_subscription_email_agents.py::test_visible_browser_session_verifies_first_email_article_before_fetch",
    ),
    "cockpit": (
        "tests/unit/test_cockpit_contract.py",
        "tests/unit/test_cockpit_candidates.py",
        "tests/unit/test_cockpit_lane_state.py",
        "tests/unit/test_lane_state.py",
        "tests/unit/test_cockpit_no_demo_data.py",
        "tests/unit/test_cockpit_routes.py",
        "tests/unit/test_cockpit_panels.py",
    ),
    "process": (
        "tests/unit/test_cockpit_clearance.py",
        "tests/unit/test_cockpit_legacy_reconciliation.py",
        "tests/unit/test_dashboard_live_data_qa_script.py",
        "tests/unit/test_ops_scripts.py::test_user_process_audit_accepts_focused_execution_contract",
        "tests/unit/test_ops_scripts.py::test_user_process_audit_detects_buried_execution_focus",
    ),
    "institutional": (
        "tests/unit/test_institutional_signal.py",
        "tests/unit/test_signal_evidence.py::test_institutional_signal_inspector_names_holder_changes_and_ratio_basis",
        "tests/unit/test_actionability_gate.py::test_actionability_gate_rejects_confirmed_signal_demoted_by_own_lane_gate",
        "tests/unit/test_actionability_gate.py::test_actionability_gate_caps_institutional_at_context_only",
    ),
}

STATIC_PRODUCTION_PATHS = (
    PROJECT_ROOT / "src" / "agency" / "views" / "cockpit.py",
    PROJECT_ROOT / "src" / "agency" / "templates" / "cockpit.html",
    PROJECT_ROOT / "src" / "agency" / "templates" / "_cockpit_panels.html",
    PROJECT_ROOT / "src" / "agency" / "static" / "cockpit.js",
    PROJECT_ROOT / "scripts" / "check_cockpit_ux_qa.py",
    PROJECT_ROOT / "scripts" / "check_dashboard_live_data_qa.py",
)
STATIC_RUNTIME_PATHS = STATIC_PRODUCTION_PATHS[:4]

FORBIDDEN_OPERATIONAL_TOKENS = (
    "window.COCKPIT_DATA",
    "EDITMODE",
    "C-14:32",
    "grossPostTrade",
    "Health Monitor Fallback",
    "Fallback Thesis",
    "Fallback Analysis",
    "recent mailbox sample",
    "first-version",
    "hidden artifact fallback",
    "artifact_fallback",
)
QA_GUARDRAIL_TOKENS = {
    "Health Monitor Fallback",
    "Fallback Thesis",
    "Fallback Analysis",
    "recent mailbox sample",
    "first-version",
}

GENERIC_SIGNAL_TEXT = (
    "Bullish signal detected.",
    "Bearish signal detected.",
    "Signal was recorded.",
    "Evidence available in audit.",
    "Ready for review.",
)


@dataclass(frozen=True)
class CheckResult:
    group: str
    name: str
    passed: bool
    detail: str
    evidence: str = ""


@dataclass(frozen=True)
class CommandResult:
    group: str
    command: list[str]
    returncode: int
    stdout_tail: str
    stderr_tail: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


Runner = Callable[[str, Sequence[str]], CommandResult]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    selected_groups = _selected_groups(args.group)
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    output_root.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC)
    semantic_results = run_semantic_checks()
    command_results: list[CommandResult] = []
    if not args.skip_pytest:
        command_results = run_pytest_groups(selected_groups)

    summary = _summary_payload(
        started_at=started_at,
        selected_groups=selected_groups,
        semantic_results=semantic_results,
        command_results=command_results,
    )
    summary_path = output_root / "ux-preservation-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    report_path = output_root / "ux-preservation-summary.md"
    report_path.write_text(_markdown_report(summary), encoding="utf-8")
    if args.audit_path:
        audit_path = Path(args.audit_path)
        if not audit_path.is_absolute():
            audit_path = PROJECT_ROOT / audit_path
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(_markdown_report(summary), encoding="utf-8")

    if summary["status"] == "PASS":
        print(f"UX preservation PASS: {len(semantic_results)} semantic checks")
        print(f"Artifact: {_display_path(summary_path)}")
        return 0
    print("UX preservation FAIL")
    for failure in summary["failures"]:
        print(f"- [{failure['group']}] {failure['name']}: {failure['detail']}")
    print(f"Artifact: {_display_path(summary_path)}")
    return 1


def run_semantic_checks(
    *,
    cockpit_sources: Mapping[str, object] | None = None,
    detail_context: Mapping[str, object] | None = None,
) -> list[CheckResult]:
    from agency.runtime.signal_evidence import (
        _block_trade_evidence,
        _fundamentals_evidence,
        _institutional_evidence,
        _unusual_trade_evidence,
    )
    from agency.views.cockpit import (
        cockpit_context_from_sources,
        cockpit_ticker_detail_payload_from_context,
    )

    results: list[CheckResult] = []
    sources = cockpit_sources or rich_cockpit_sources()
    context = cockpit_context_from_sources(sources)
    candidates = _mapping_list(context.get("candidates"))
    data_state = _mapping(context.get("data_state"))
    candidate_by_ticker = {str(row.get("ticker")): row for row in candidates}
    rich = candidate_by_ticker.get("RICH", {})
    rank_11 = next((row for row in candidates if row.get("rank") == 11), {})

    results.extend(
        [
            _check(
                "candidate",
                "candidate ranking remains conviction-sorted",
                [row.get("ticker") for row in candidates[:3]] == ["RICH", "TRF", "EMAIL"],
                f"top three tickers were {[row.get('ticker') for row in candidates[:3]]}",
            ),
            _check(
                "candidate",
                "candidate evidence keeps concrete hard values",
                "+4.2%" in str(rich.get("evidence_line"))
                and "2.8x" in str(rich.get("evidence_line"))
                and rich.get("evidence_hard_value") == "+4.2%"
                and not _contains_any(str(rich.get("evidence_line")), GENERIC_SIGNAL_TEXT),
                str(rich.get("evidence_line")),
            ),
            _check(
                "candidate",
                "focused execution route keeps selected ticker",
                str(rich.get("execution_focus_url")).endswith(
                    "/execution-preview?ticker=RICH#focused-preview-RICH"
                ),
                str(rich.get("execution_focus_url")),
            ),
            _check(
                "candidate",
                "candidate actionability and controls stay tied to order readiness",
                rich.get("actionable") is True
                and rich.get("status") == "approved"
                and rich.get("decision_controls") == ["order"]
                and rich.get("order_preview") == "$4,200",
                str(
                    {
                        "actionable": rich.get("actionable"),
                        "status": rich.get("status"),
                        "decision_controls": rich.get("decision_controls"),
                        "order_preview": rich.get("order_preview"),
                    }
                ),
            ),
            _check(
                "candidate",
                "candidate keeps deterministic and LLM score fields",
                rich.get("det_conviction") == 0.91
                and rich.get("llm_conviction") == 0.83
                and rich.get("llm_label") == "LLM agrees"
                and rich.get("evidence_tiers") == ["confirmed"],
                str(
                    {
                        "det_conviction": rich.get("det_conviction"),
                        "llm_conviction": rich.get("llm_conviction"),
                        "llm_label": rich.get("llm_label"),
                        "evidence_tiers": rich.get("evidence_tiers"),
                    }
                ),
            ),
            _check(
                "candidate",
                "manual LLM wording is preserved outside top 10",
                "outside the top 10 automatic review set" in str(rank_11.get("llm_label")),
                str(rank_11.get("llm_label")),
            ),
        ]
    )

    lane_rows = _mapping_list(data_state.get("lane_rows"))
    lane_by_id = {str(row.get("lane_id")): row for row in lane_rows}
    rendered_data_state = json.dumps(data_state, sort_keys=True).lower()
    subscription_lane = lane_by_id.get("subscription_thesis", {})
    live_lane = lane_by_id.get("massive_live_trade_slices", {})
    options_lane = lane_by_id.get("massive_options_flow", {})
    results.extend(
        [
            _check(
                "lane-state",
                "operator wording does not expose stale jargon",
                "stale" not in rendered_data_state and "needs refresh" in rendered_data_state,
                "data_state text is sanitized",
            ),
            _check(
                "lane-state",
                "live lane exposes individual scheduler refresh action",
                _mapping(live_lane.get("refresh_action")).get("url")
                == "/scheduler/massive-lanes/massive_live_trade_slices/refresh",
                str(_mapping(live_lane.get("refresh_action"))),
            ),
            _check(
                "lane-state",
                "subscription lane uses login refresh action",
                _mapping(subscription_lane.get("refresh_action")).get("url")
                == "/scheduler/subscription-emails/login-refresh",
                str(_mapping(subscription_lane.get("refresh_action"))),
            ),
            _check(
                "lane-state",
                "optional disabled lane is not presented as a blocker",
                options_lane.get("blocker") is False
                and _mapping(options_lane.get("refresh_action")).get("url") == "",
                str(options_lane),
            ),
        ]
    )

    detail_payload = cockpit_ticker_detail_payload_from_context(
        detail_context or rich_candidate_detail_context()
    )
    signals = _mapping_list(detail_payload.get("signals"))
    hard_evidence = " | ".join(str(signal.get("hard_evidence")) for signal in signals)
    context_cards = _mapping_list(detail_payload.get("context_cards"))
    results.extend(
        [
            _check(
                "candidate-detail",
                "detail drawer preserves TRF/off-exchange hard evidence",
                "$440.0M" in hard_evidence and "TRF/off-exchange" in hard_evidence,
                hard_evidence,
            ),
            _check(
                "candidate-detail",
                "detail drawer preserves subscription email context",
                any(card.get("label") == "Subscription email" for card in context_cards)
                and "mapped to RICH" in json.dumps(context_cards),
                json.dumps(context_cards, sort_keys=True),
            ),
            _check(
                "candidate-detail",
                "email evidence fixture carries article judgement contract",
                "linked_content_status" in _mapping(detail_context or rich_candidate_detail_context()).get(
                    "email_evidence", {}
                )
                and "decision_use" in _mapping(detail_context or rich_candidate_detail_context()).get(
                    "email_evidence", {}
                )
                and "judgement_contribution" in _mapping(
                    detail_context or rich_candidate_detail_context()
                ).get("email_evidence", {}),
                str(_mapping(detail_context or rich_candidate_detail_context()).get("email_evidence", {})),
            ),
            _check(
                "candidate-detail",
                "manual LLM action remains available when report timestamp exists",
                _mapping(detail_payload.get("llm")).get("manual_review_action")
                == "/candidates/RICH/llm-review",
                str(_mapping(detail_payload.get("llm"))),
            ),
        ]
    )

    as_of = date(2026, 6, 1)
    fundamentals = _fundamentals_evidence(
        {"ticker": "RICH", "lane_key": "fundamentals", "source": "sec_company_facts"},
        rich_fundamentals_detail(),
        as_of,
    )
    institutional = _institutional_evidence(
        {"ticker": "RICH", "lane_key": "institutional", "source": "sec_13f"},
        rich_institutional_detail(),
        as_of,
    )
    block_trade = _block_trade_evidence(
        {
            "ticker": "RICH",
            "lane_key": "block_trade_pressure",
            "source": "massive_live_trade_slices",
            "direction": "BULLISH",
            "confidence_pct": 86,
            "timestamp_as_of": "2026-06-01T18:35:05+00:00",
        },
        rich_block_trade_detail(),
        as_of,
        "block_trade_pressure",
    )
    unusual = _unusual_trade_evidence(
        {
            "ticker": "RICH",
            "lane_key": "unusual_trade_activity",
            "source": "massive_live_trade_slices",
            "direction": "BULLISH",
            "confidence_pct": 78,
            "timestamp_as_of": "2026-06-01T18:35:05+00:00",
        },
        rich_unusual_trade_detail(),
        as_of,
        "unusual_trade_activity",
    )
    semantic_text = json.dumps(
        {
            "fundamentals": fundamentals,
            "institutional": institutional,
            "block_trade": block_trade,
            "unusual": unusual,
        },
        sort_keys=True,
    )
    results.extend(
        [
            _check(
                "signal-evidence",
                "fundamentals explain trend and user meaning",
                "Revenue increased 11.0%" in semantic_text
                and "bullish because operations generated cash" in semantic_text,
                str(fundamentals.get("trigger_detail")),
            ),
            _check(
                "signal-evidence",
                "institutional evidence names holder changes and ratio basis",
                "Northstar Capital" in semantic_text
                and "+750,000" in semantic_text
                and "share-count ratios, not price returns" in semantic_text,
                str(institutional.get("trigger_headline")),
            ),
            _check(
                "signal-evidence",
                "block trade evidence explains TRF/off-exchange not venue proof",
                "$440.00M" in semantic_text
                and "not proof of a dark-pool venue" in semantic_text,
                str(block_trade.get("trigger_detail")),
            ),
            _check(
                "signal-evidence",
                "unusual trade evidence identifies what was unusual",
                "notional was most unusual" in semantic_text
                and "$480.00M latest vs $120.00M median" in semantic_text,
                str(unusual.get("trigger_headline")),
            ),
        ]
    )

    results.extend(_static_production_checks())
    return results


def run_pytest_groups(
    groups: Sequence[str],
    *,
    runner: Runner | None = None,
) -> list[CommandResult]:
    active_runner = runner or _run_pytest_group
    return [active_runner(group, PYTEST_GROUPS[group]) for group in groups]


def rich_cockpit_sources() -> dict[str, object]:
    rich_candidate = _candidate(
        "RICH",
        0.91,
        "Price closed +4.2% while daily volume ran 2.8x the 30-day median.",
    )
    rich_candidate.update(
        {
            "llm_status_label": "LLM agrees",
            "llm_score_label": "0.83",
            "llm_rationale": "LLM agrees because price, flow, and email evidence corroborate.",
        }
    )
    review_queue = [
        rich_candidate,
        _candidate("TRF", 0.88, "TRF/off-exchange prints totaled $440.0M with +72.0% signed pressure."),
        _candidate("EMAIL", 0.84, "Subscription thesis mapped two articles to EMAIL with 82% confidence."),
    ]
    review_queue.extend(
        _candidate(f"T{i:02d}", 0.83 - i * 0.02, f"T{i:02d} evidence includes {i + 1}.0x metric.")
        for i in range(1, 10)
    )
    return {
        "dashboard": {
            "broker_status": {"status_label": "Connected", "status_class": "pass"},
            "data_load_status": {
                "cycle_id": "cycle-preservation-20260601",
                "overall_percent": 93,
                "critical_lane_percent": 87,
                "expected_ticker_count": 168,
                "review_operational_ready": True,
                "tradable_ready": False,
                "blocker_count": 0,
                "warning_count": 2,
                "as_of": "2026-06-01",
                "lane_states": [
                    {
                        "lane_id": "massive_live_trade_slices",
                        "lane_kind": "raw_acquisition",
                        "label": "Massive Live Trade Slices",
                        "status_label": "Data is still loading",
                        "status_class": "warn",
                        "state": "loading",
                        "operator_message": (
                            "Massive Live Trade Slices data is still loading "
                            "(144/168 ticker-days)."
                        ),
                        "recommended_action": (
                            "Wait for this lane to finish, or refresh Live Trade Slices "
                            "through the scheduler."
                        ),
                        "progress_label": "144/168 ticker-days",
                        "eta_label": "9m",
                        "latest_as_of": "2026-06-01T18:33:44+00:00",
                        "checked_at": "2026-06-01T18:35:30+00:00",
                        "required_now": True,
                        "blocks_execution": True,
                        "blocker": False,
                        "ready_for_review": True,
                        "ready_for_paper_execution": False,
                        "raw_lanes_required": [],
                        "source_dataset": "stock_trades",
                    },
                    {
                        "lane_id": "subscription_thesis",
                        "lane_kind": "derived_signal",
                        "label": "Subscription Thesis",
                        "status_label": "Lane Stale",
                        "status_class": "warn",
                        "state": "stale",
                        "operator_message": "Subscription Thesis is stale after new article evidence.",
                        "progress_label": "17/168 row(s)",
                        "latest_as_of": "2026-06-01T16:15:00+00:00",
                        "checked_at": "2026-06-01T18:35:30+00:00",
                        "required_now": True,
                        "blocks_execution": False,
                        "blocker": False,
                        "ready_for_review": True,
                        "ready_for_paper_execution": False,
                        "source_dataset": "subscription_emails",
                    },
                    {
                        "lane_id": "massive_options_flow",
                        "lane_kind": "raw_acquisition",
                        "label": "Massive Options Flow",
                        "status_label": "Not required for current workflow",
                        "status_class": "neutral",
                        "state": "disabled_optional",
                        "operator_message": "Options flow is optional for the current workflow.",
                        "progress_label": "not tracked",
                        "latest_as_of": "not recorded",
                        "checked_at": "2026-06-01T18:35:30+00:00",
                        "required_now": False,
                        "blocks_execution": False,
                        "blocker": False,
                        "ready_for_review": False,
                        "ready_for_paper_execution": False,
                        "source_dataset": "options_flow",
                    },
                ],
            },
            "full_live_readiness": {
                "cycle_id": "cycle-preservation-20260601",
                "ready": True,
                "tradable_ready": False,
                "source_count": 11,
                "fresh_source_count": 9,
                "blocker_count": 0,
                "warning_count": 2,
                "status_label": "Ready with cautions",
                "status_class": "warn",
            },
            "review_progress": {
                "total_count": len(review_queue),
                "pending_count": len(review_queue),
                "approve_count": 0,
                "reviewed_count": 0,
            },
            "review_queue": review_queue,
            "data_sources": [
                {
                    "name": "Massive live trade slices",
                    "status_label": "Loaded",
                    "status_class": "pass",
                    "checked_at": "2026-06-01T18:35:30+00:00",
                    "coverage_label": "168/168 tickers",
                    "detail": "Live-slice lane proof is current for the active universe.",
                }
            ],
            "policy_summary": {
                "max_gross_exposure_pct": 100,
                "cash_reserve_pct": 10,
                "largest_name_cap_pct": 25,
            },
        },
        "execution": {
            "orderable_rows": [{"ticker": "RICH", "preview_state": "READY", "side": "BUY"}],
            "preview_rows": [
                {
                    "ticker": "RICH",
                    "preview_state": "READY",
                    "side": "BUY",
                    "submit_enabled": True,
                    "notional_label": "$4,200",
                    "order_intent_hash": "hash-rich",
                }
            ],
            "summary": {
                "orderable_count": 1,
                "status_label": "One paper preview ready",
                "status_class": "pass",
            },
        },
        "portfolio": {"positions": [], "summary": {"gross_exposure_pct": 22, "cash_reserve_pct": 58}},
        "market": {
            "broker": {
                "account": {"buying_power": 25_000, "cash": 58_000, "equity": 100_000},
                "gross_exposure_pct": 22,
                "status_label": "Connected",
            }
        },
        "signals": {"lanes": []},
    }


def rich_candidate_detail_context() -> dict[str, object]:
    return {
        "ticker": "RICH",
        "decision_brief": {
            "headline": "RICH has actionable evidence from volume, TRF flow, and subscription thesis.",
            "detail": (
                "Volume, off-exchange pressure, and article thesis all point in the same "
                "direction; review order sizing before paper submit."
            ),
            "next_step": "Approve the order intent only after checking lane timestamps.",
            "action_label": "BUY",
            "state_label": "Ready for paper execution",
            "conviction_pct": 91,
            "source_count": 6,
            "confirmed_signal_count": 4,
            "support_cards": [
                {
                    "label": "Volume expansion",
                    "detail": "2.8x median daily volume with +4.2% close-to-close return.",
                    "meta": "prices_daily",
                    "tone": "pass",
                }
            ],
            "caution_cards": [
                {
                    "label": "Execution freshness",
                    "detail": "Live trade slice is review-ready but not yet paper-execution ready.",
                    "meta": "massive_live_trade_slices",
                    "tone": "warn",
                }
            ],
            "decision_points": [
                {
                    "label": "Paper sizing",
                    "detail": "$4,200 proposed notional under position cap.",
                    "meta": "risk",
                    "tone": "pass",
                }
            ],
            "signal_mix_note": "4 bullish confirmed signals, 1 caution.",
        },
        "latest_report": {
            "cycle_id": "cycle-preservation-20260601",
            "as_of": "2026-06-01T18:35:30+00:00",
            "generated_at": "2026-06-01T18:36:00+00:00",
            "action": "BUY",
            "llm_status_label": "LLM agrees",
            "llm_action": "AGREE",
            "llm_confidence_pct": 83,
            "llm_rationale": "LLM agrees because price, flow, and subscription evidence corroborate.",
            "actionable_signals": [
                {
                    "display_name": "Block Trade Pressure",
                    "direction": "BULLISH",
                    "score": "0.74",
                    "confidence_pct": "86",
                    "source": "massive_live_trade_slices",
                    "timestamp_as_of": "2026-06-01T18:35:05+00:00",
                    "trigger_headline": (
                        "RICH block trade pressure is bullish: 4 TRF/off-exchange prints "
                        "totaled $440.0M."
                    ),
                    "trigger_detail": (
                        "TRF/off-exchange prints are useful large-print evidence, not proof "
                        "of a dark-pool venue."
                    ),
                    "trigger_cards": [
                        {"label": "TRF/off-exchange", "value": "4 / $440.0M"},
                        {"label": "Directional read", "value": "+72.0% buy-side"},
                    ],
                },
                {
                    "display_name": "Unusual Trade Activity",
                    "direction": "BULLISH",
                    "score": "0.69",
                    "confidence_pct": "78",
                    "source": "massive_live_trade_slices",
                    "timestamp_as_of": "2026-06-01T18:35:05+00:00",
                    "trigger_headline": (
                        "RICH identified unusual trade activity: notional and share volume "
                        "were most unusual."
                    ),
                    "trigger_cards": [
                        {"label": "Most unusual metric", "value": "Notional and share volume"},
                        {"label": "Notional anomaly", "value": "4.0x"},
                    ],
                },
            ],
            "context_signals": [],
            "suppressed_signals": [],
        },
        "review": {"decision": "Pending"},
        "data_health": {
            "status_label": "Ready with cautions",
            "status_class": "warn",
            "headline": "Review proof is current; paper execution waits for final live lane proof.",
            "recommended_action": "Refresh Live Trade Slices before paper submit.",
            "overall_percent": 93,
            "last_verified_label": "2026-06-01 18:35 UTC",
        },
        "email_evidence": {
            "meaning": "Email evidence synced",
            "detail": "Two Seeking Alpha articles were mapped to RICH with bullish thesis confidence.",
            "status_class": "pass",
            "linked_content_status": "article_analyzed",
            "article_count": 2,
            "decision_use": "Treat as context-only bullish thesis until corroborated by market data.",
            "judgement_contribution": (
                "Supports the current RICH Buy judgment because article thesis, price action, "
                "and flow pressure agree."
            ),
            "local_llm_article_status": "completed",
            "local_llm_article_direction": "BULLISH",
            "local_llm_article_confidence": 0.82,
        },
        "news_evidence": {
            "meaning": "RSS evidence resolved",
            "detail": "Generic RSS headline was resolved to RICH and marked consumed.",
            "status_class": "pass",
        },
    }


def rich_fundamentals_detail() -> dict[str, object]:
    return {
        "filing_period": "Q1",
        "filing_year": 2026,
        "filing_form": "10-Q",
        "filing_period_end": "2026-03-31",
        "period_alignment_status": "aligned",
        "quality_score": 0.71,
        "growth_score": 0.64,
        "valuation_score": -0.08,
        "forward_score": 0.22,
        "composite_score": 0.58,
        "gross_margin": 0.52,
        "operating_margin": 0.31,
        "net_margin": 0.24,
        "fcf_margin": 0.18,
        "roe": 0.42,
        "roa": 0.19,
        "leverage": 0.44,
        "revenue_growth_yoy": 0.11,
        "net_income_growth_yoy": 0.16,
        "fcf_growth_yoy": 0.21,
        "trailing_pe": 31.4,
        "forward_pe": 25.2,
        "forward_eps": 7.31,
        "eps_beat_rate": 0.78,
        "analyst_count": 31,
        "forward_data_status": "ready",
        "forward_data_as_of": "2026-06-01T12:00:00+00:00",
    }


def rich_institutional_detail() -> dict[str, object]:
    return {
        "quarter_end_date": "2026-03-31",
        "holder_count": 4,
        "total_shares_held": 12_400_000,
        "previous_shares_held": 10_000_000,
        "total_change_from_prev_quarter": 2_400_000,
        "net_change_current_share_ratio": 0.1935,
        "net_change_prior_share_ratio": 0.24,
        "total_value_usd_thousands": 1_860_000,
        "institutional_score": 0.72,
        "holder_changes": [
            {
                "holder_name": "Northstar Capital",
                "current_shares": 2_000_000,
                "previous_shares": 1_250_000,
                "change_from_prev_quarter": 750_000,
                "value_usd_thousands": 300_000,
            },
            {
                "holder_name": "Harbor Ridge Advisors",
                "current_shares": 1_600_000,
                "previous_shares": 1_180_000,
                "change_from_prev_quarter": 420_000,
                "value_usd_thousands": 250_000,
            },
        ],
    }


def rich_block_trade_detail() -> dict[str, object]:
    return {
        "block_trade_pressure": 0.74,
        "trade_count": 1_250,
        "total_volume": 8_800_000,
        "total_notional": 880_000_000,
        "signed_notional": 633_600_000,
        "focus_trade_count": 4,
        "focus_notional": 440_000_000,
        "signed_focus_notional": 316_800_000,
        "focus_notional_share": 0.50,
        "block_count": 3,
        "off_exchange_count": 4,
        "trf_off_exchange_count": 4,
        "trf_off_exchange_notional": 440_000_000,
        "largest_focus_notional": 180_000_000,
        "largest_focus_notional_multiple": 6.2,
        "net_notional_pressure": 0.72,
        "block_notional_threshold": 30_000_000,
        "block_size_threshold": 250_000,
        "pre_market_volume": 120_000,
    }


def rich_unusual_trade_detail() -> dict[str, object]:
    return {
        "unusual_trade_activity": 0.69,
        "trade_count_anomaly_ratio": 2.2,
        "notional_anomaly_ratio": 4.0,
        "volume_anomaly_ratio": 3.6,
        "latest_activity_notional": 480_000_000,
        "baseline_activity_notional_median": 120_000_000,
        "latest_activity_volume": 4_800_000,
        "baseline_activity_volume_median": 1_333_333,
        "latest_activity_trade_count": 2_200,
        "baseline_activity_trade_count_median": 1_000,
        "latest_net_notional_pressure": 0.64,
        "latest_signed_notional": 307_200_000,
        "block_count": 1,
        "off_exchange_count": 2,
    }


def _candidate(ticker: str, score: float, evidence: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "company": f"{ticker} Preservation Corp",
        "sector": "Technology",
        "final_action": "BUY",
        "final_score": score,
        "deterministic_score_label": f"{score:.2f}",
        "risk_status_label": "PASS",
        "risk_detail": "No major risk flag in current pack.",
        "top_reasons": [evidence],
        "review_status_label": "Needs review",
        "is_reviewable": True,
        "cycle_id": "cycle-preservation-20260601",
        "as_of": "2026-06-01T18:35:30+00:00",
    }


def _static_production_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    for token in FORBIDDEN_OPERATIONAL_TOKENS:
        paths = STATIC_RUNTIME_PATHS if token in QA_GUARDRAIL_TOKENS else STATIC_PRODUCTION_PATHS
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        results.append(
            _check(
                "static",
                f"production cockpit does not expose {token}",
                token not in combined,
                f"searched {len(paths)} production files",
            )
        )
    return results


def _run_pytest_group(group: str, paths: Sequence[str]) -> CommandResult:
    command = [sys.executable, "-m", "pytest", "-q", *paths]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        group=group,
        command=command,
        returncode=completed.returncode,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
    )


def _selected_groups(group: str) -> list[str]:
    if group == "all":
        return list(PYTEST_GROUPS)
    if group not in PYTEST_GROUPS:
        raise SystemExit(f"Unknown group {group!r}; choose all or one of {', '.join(PYTEST_GROUPS)}")
    return [group]


def _summary_payload(
    *,
    started_at: datetime,
    selected_groups: Sequence[str],
    semantic_results: Sequence[CheckResult],
    command_results: Sequence[CommandResult],
) -> dict[str, object]:
    semantic_failures = [result for result in semantic_results if not result.passed]
    command_failures = [result for result in command_results if not result.passed]
    failures = [
        {
            "group": result.group,
            "name": result.name,
            "detail": result.detail,
            "evidence": result.evidence,
        }
        for result in semantic_failures
    ]
    failures.extend(
        {
            "group": result.group,
            "name": "pytest preservation bundle",
            "detail": f"pytest exited {result.returncode}",
            "evidence": result.stdout_tail or result.stderr_tail,
        }
        for result in command_failures
    )
    return {
        "schema_version": "0.1.0",
        "ticket": "UXC-014",
        "status": "PASS" if not failures else "FAIL",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "groups": list(selected_groups),
        "definition_of_done": (
            "One command gives clear preservation PASS/FAIL and identifies the protected "
            "behavior that changed."
        ),
        "semantic_checks": [asdict(result) for result in semantic_results],
        "pytest_commands": [asdict(result) for result in command_results],
        "tests_run": [path for group in selected_groups for path in PYTEST_GROUPS[group]],
        "screenshots_captured": [],
        "prototype_compared": (
            "No browser screenshot in this preservation command; run check_cockpit_ux_qa "
            "for visual prototype comparison."
        ),
        "accepted_deltas": [],
        "failures": failures,
    }


def _markdown_report(summary: Mapping[str, object]) -> str:
    lines = [
        "# UXC-014 Preservation Regression Harness",
        "",
        f"- Status: **{summary['status']}**",
        f"- Ticket: {summary['ticket']}",
        f"- Started: {summary['started_at']}",
        f"- Finished: {summary['finished_at']}",
        f"- Groups: {', '.join(str(group) for group in _list(summary.get('groups')))}",
        "",
        "## Definition Of Done",
        "",
        str(summary["definition_of_done"]),
        "",
        "## Protected Checks",
        "",
    ]
    for check in _list(summary.get("semantic_checks")):
        item = _mapping(check)
        status = "PASS" if item.get("passed") is True else "FAIL"
        lines.append(
            f"- {status} [{item.get('group')}] {item.get('name')} - {item.get('detail')}"
        )
    lines.extend(["", "## Pytest Bundles", ""])
    for command in _list(summary.get("pytest_commands")):
        item = _mapping(command)
        status = "PASS" if int(item.get("returncode") or 0) == 0 else "FAIL"
        lines.append(f"- {status} [{item.get('group')}] `{' '.join(_list(item.get('command')))}`")
    lines.extend(["", "## Visual Artifacts", ""])
    lines.append(f"- Screenshots captured: {len(_list(summary.get('screenshots_captured')))}")
    lines.append(f"- Prototype compared: {summary.get('prototype_compared')}")
    lines.append(f"- Accepted deltas: {len(_list(summary.get('accepted_deltas')))}")
    failures = _list(summary.get("failures"))
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            item = _mapping(failure)
            lines.append(f"- [{item.get('group')}] {item.get('name')}: {item.get('detail')}")
    return "\n".join(lines) + "\n"


def _check(group: str, name: str, passed: bool, detail: str, evidence: str = "") -> CheckResult:
    return CheckResult(group=group, name=name, passed=passed, detail=detail, evidence=evidence)


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _tail(text: str, *, max_chars: int = 4_000) -> str:
    clean = text.strip()
    return clean[-max_chars:] if len(clean) > max_chars else clean


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run UX preservation regression checks.")
    parser.add_argument(
        "--group",
        choices=("all", *PYTEST_GROUPS.keys()),
        default="all",
        help="Preservation bundle to run.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Directory for generated JSON/Markdown artifacts.",
    )
    parser.add_argument(
        "--audit-path",
        default=str(DEFAULT_AUDIT_PATH),
        help="Optional committed audit markdown path. Use empty string to skip.",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Run only in-process semantic checks; intended for script unit tests.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
