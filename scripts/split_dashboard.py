"""Split dashboard.py into per-page view modules.

One-shot refactor script. Strategy:
- `_shared.py` holds constants + utilities used by 2+ modules. It imports
  nothing from other view modules or dashboard -> a true leaf.
- Each view module imports constants/utilities from `_shared` at top level,
  and resolves cross-module function references via lazy (function-local)
  imports to avoid any import-time cycles.
- `dashboard.py` keeps routes + the 3 `_dashboard_*` context fetchers, and
  imports the public helpers it needs from the view modules.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DASH = REPO_ROOT / "src" / "agency" / "dashboard.py"
VIEWS = REPO_ROOT / "src" / "agency" / "views"

# Functions that stay in dashboard.py (route handlers only).
ROUTES_STAY = [
    "dashboard",
    "paper_review_status",
    "operational_readiness_status",
    "lane_promotion_status",
    "scheduler_work_queue_status",
    "candidate_detail",
    "record_candidate_review",
    "final_selection",
    "risk",
    "execution_preview",
    "approve_execution_order",
    "submit_execution_order",
    "policy",
    "portfolio_monitor",
    "signals",
    "market_regime",
    "universe",
    "record_portfolio_snapshot",
    "broker_status",
    "learning",
]

# Module-level constants -> all move to _shared.py
SHARED_CONSTANTS = [
    "REPO_ROOT",
    "EMAIL_EVENTS_PATH",
    "NEWS_RSS_PATH",
    "PRICES_DAILY_ROOT",
    "ACTIONABLE_ACTIONS",
    "OPEN_RISK_DECISIONS",
    "DEGRADED_SOURCE_STATUSES",
    "DEGRADED_FRESHNESS",
    "FINAL_SELECTION_REPORT_LIMIT",
    "SIGNALS_REPORT_LIMIT",
    "SIGNALS_CONTEXT_CACHE_SECONDS",
    "MARKET_REGIME_CONTEXT_CACHE_SECONDS",
    "LIVE_PIT_CYCLE_PREFIX",
    "LIVE_READY_CYCLE_PREFIX",
    "LIVE_SELECTION_CYCLE_PREFIXES",
    "MAX_FULL_CYCLE_LABEL_LENGTH",
    "CYCLE_LABEL_SUFFIX_LENGTH",
    "MIN_BRIEF_SOURCE_COUNT",
    "MIN_BRIEF_CONFIRMED_COUNT",
    "MIN_EMAIL_PAIR_SCORE",
    "EMAIL_FEED_SOURCE_ID_PARTS",
    "EMAIL_FEED_SOURCE_ID_CORE_PARTS",
    "HUMAN_LIST_PAIR_COUNT",
    "EMAIL_LINKED_STATUS_PRIORITY",
    "EMAIL_ANALYZED_STATUSES",
    "EMAIL_ASSET_EXTENSIONS",
    "EMAIL_ASSET_DOMAIN_PREFIXES",
    "EMAIL_HEADLINE_FOCUS_RE",
    "EMAIL_EVENT_LABELS",
]

# Module-level mutable caches owned by specific modules.
MODULE_CACHES = {
    "signals": [("_signals_context_cache", "dict[str, tuple[float, dict[str, object]]]")],
    "market_regime": [("_market_regime_context_cache", "dict[str, tuple[float, dict[str, object]]]")],
}

# module name -> ordered list of function names that belong to it
MODULES = {
    "_shared": [
        "_dashboard_selection_reports",
        "_dashboard_risk_decisions",
        "_dashboard_candidate_timeline",
        "_lifecycle_events_for_reports",
        "_timeline_lifecycle_events_for_reports",
        "_label_text",
        "_clip_text",
        "_clean_text",
        "_row_text",
        "_format_timestamp_label",
        "_timestamp_sort_value",
        "_parse_dashboard_timestamp",
        "_dedupe_text",
        "_source_id_core",
        "_same_pair_text",
        "_pair_text",
        "_plural",
        "_reason_text",
        "_string_list",
        "_list_field",
        "_mapping_field",
        "_mapping_list_field",
        "_optional_float_field",
        "_float_field",
        "_int_field",
        "_percent",
        "_env_bool_text",
        "_now_utc_text",
        "_is_actionable_candidate",
        "_runtime_payload_key",
        "_matching_payload",
        "_score_text",
        "_short_cycle_label",
        "_active_cycle_reports",
        "_selection_reports_for_cycle",
        "_latest_selection_cycle_id",
        "_risk_decisions_for_reports",
        "_decision_class",
        "_direction_class",
        "_source_is_degraded",
        "_human_list",
        "_sorted_signals",
        "_service_label",
        "_human_review_key",
        "_human_review_summary",
        "_human_review_index",
        "_human_review_status_class",
        "_numeric_value",
        "_reason_summary",
    ],
    "learning": [
        "learning_context",
        "_learning_price_history",
        "learning_summary",
    ],
    "portfolio": [
        "portfolio_monitor_context",
        "portfolio_monitor_summary",
        "portfolio_snapshot_rows",
        "_broker_account",
        "_broker_positions",
        "_broker_orders",
        "_broker_gross_exposure_pct",
        "_pending_opening_order_exposure_pct",
        "_order_is_pending_opening",
        "_order_pending_notional",
        "_position_for_order",
        "_position_is_long",
        "_position_is_short",
        "_numeric_mapping_field",
        "_broker_ready_for_paper_promotion",
        "_portfolio_execution_detail",
        "_portfolio_headline",
        "_broker_execution_enabled",
    ],
    "market_regime": [
        "market_regime_context",
        "broker_status_context",
        "_cached_market_regime_context",
        "_store_market_regime_context",
    ],
    "signals": [
        "signals_context",
        "_cached_signals_context",
        "_store_signals_context",
        "signal_dashboard_rows",
        "signal_lane_rows",
        "signal_dashboard_summary",
        "_context_signal_rows",
        "_signal_rows",
        "_signal_lane_row",
        "_signal_dashboard_sort_key",
        "_signal_lane_sort_key",
        "_signal_bucket_label",
        "_signal_bucket_class",
        "_signal_actionability_class",
        "_freshness_class",
        "_lane_state_class",
        "_signal_reason_text",
        "_signal_reason_codes_label",
        "_signal_inspection_fields",
        "_signal_interpretation_text",
        "_signal_decision_effect_text",
        "_signal_decision_alignment_text",
        "_signal_quality_text",
        "_signal_provenance_text",
        "_average_int",
        "_average_float",
        "_signals_headline",
        "_decision_explanation",
        "_signal_group_summary",
        "_signal_summary",
        "_signal_source",
    ],
    "risk": [
        "risk_context",
        "risk_decision_rows",
        "risk_summary",
        "_risk_decision_row",
        "_gate_status",
        "_gate_rows",
        "_check_rows",
        "_gate_label",
        "_gate_criteria",
        "_gate_meaning",
        "_gate_next_step",
        "_selection_gate_summary",
        "_risk_decision_title",
        "_risk_decision_meaning",
        "_risk_user_action",
        "_risk_primary_issue",
        "_risk_plain_check_summary",
        "_risk_next_step",
        "_risk_row_sort_key",
        "_risk_headline",
        "_risk_summary_next_action",
        "_risk_flag_count",
    ],
    "execution": [
        "execution_preview_context",
        "execution_preview_order_row",
        "execution_approval_keys",
        "order_approval_keys_for_reports",
        "order_approval_events_for_reports",
        "_remove_research_only_promoted_order_approvals",
        "_report_requires_separate_order_approval",
        "_record_submitted_order",
        "execution_preview_rows",
        "execution_preview_summary",
        "leveraged_alternative_panel",
        "_execution_preview_row",
        "_order_approval_key",
        "_order_approval_key_from_preview",
        "_leveraged_review_sort_key",
        "_execution_preview_sort_key",
        "_execution_headline",
        "_execution_workflow_guidance",
        "_preview_state_class",
        "_execution_submit_url",
        "_execution_approve_order_url",
        "_submit_blocker",
        "_not_ready_submit_blocker",
        "_submit_label",
        "_order_value_label",
        "_money_label",
        "_execution_size_label",
        "_execution_order_intent",
        "_execution_reason_text",
        "_execution_approval_label",
        "_execution_next_step",
        "_execution_detail",
    ],
    "final_selection": [
        "final_selection_context",
        "final_selection_rows",
        "final_selection_summary",
        "_final_selection_row",
        "_final_selection_takeaway",
        "_final_caution_summary",
        "_plain_reason_rows",
        "_split_reason_codes",
        "_reason_tone",
        "_final_selection_next_step",
        "_final_selection_sort_key",
        "_candidate_detail_sort_key",
        "_descending_text_timestamp",
        "_final_selection_headline",
        "_final_selection_topbar",
        "_final_selection_detail",
        "_final_selection_scope_detail",
    ],
    "candidates": [
        "candidate_detail_context",
        "candidate_rows",
        "candidate_detail_report_rows",
        "candidate_detail_summary",
        "candidate_review_summary",
        "timeline_rows",
        "candidate_email_evidence",
        "candidate_email_evidence_with_judgement",
        "_email_event_with_judgement",
        "_email_judgement_context",
        "_email_judgement_contribution",
        "_secondary_email_contribution",
        "_direct_email_contribution",
        "_email_relation_to_judgement",
        "_email_judgement_summary",
        "_email_primary_takeaway_with_judgement",
        "_candidate_email_event_rows",
        "_normalized_linked_content_status",
        "_is_email_article_analyzed_status",
        "_email_non_article_asset_url",
        "_candidate_email_feed_rows",
        "_dedupe_email_event_rows",
        "_dedupe_email_feed_rows",
        "_email_event_dedupe_key",
        "_email_feed_dedupe_key",
        "_email_event_priority",
        "_candidate_email_paired_rows",
        "_pop_best_email_feed_match",
        "_candidate_email_match_score",
        "_candidate_email_pair_row",
        "_candidate_email_mailbox_cell",
        "_candidate_email_interpretation_cell",
        "_email_interpretation_status_label",
        "_email_interpretation_status_class",
        "_candidate_email_count",
        "_candidate_email_analyzed_count",
        "_candidate_email_feed_count",
        "_candidate_email_service_counts",
        "_candidate_email_direction_counts",
        "_ticker_frame",
        "_records",
        "_latest_text",
        "_service_summary",
        "_direction_count_rows",
        "_direction_summary",
        "_email_evidence_status",
        "_email_status_summary",
        "_email_analysis_gap_summary",
        "_email_analysis_gap_sentence",
        "_candidate_email_insight_cards",
        "_headline_thesis",
        "_email_primary_takeaway",
        "_email_balance_prefix",
        "_email_balance_contradicts_top",
        "_email_pipeline_summary",
        "_email_quality_summary",
        "_email_evidence_meaning",
        "_email_evidence_detail",
        "_email_ticker_thesis",
        "_email_ticker_relevance",
        "_email_dashboard_decision_use",
        "_email_article_focus",
        "_email_focus_ticker",
        "_email_topic_from_title",
        "_mailbox_event_summary",
        "_email_interpretation_summary",
        "_email_status_note",
        "_linked_status_label",
        "_linked_status_class",
        "_linked_status_detail",
        "_legacy_linked_thesis",
        "_object_strings",
        "_email_taxonomy_label",
        "_email_default_decision_use",
        "_sentence_case",
        "_sentence_fragment",
        "_int_or_none",
        "_email_headline",
        "_email_event_label",
        "candidate_decision_brief",
        "_empty_decision_brief",
        "_mapping_rows",
        "_candidate_state_class",
        "_candidate_state_label",
        "_candidate_action_label",
        "_candidate_brief_headline",
        "_candidate_brief_detail",
        "_first_signal_summary",
        "_candidate_next_step",
        "_signal_count_cards",
        "_signal_direction_counts",
        "_signal_balance",
        "_signal_driver_cards",
        "_decision_points",
        "_paper_review_row",
        "_candidate_row",
        "_candidate_review_redirect_url",
        "_review_action_url",
        "_paper_review_sort_key",
        "_candidate_detail_headline",
        "_candidate_detail_text",
        "_paper_review_state",
        "_paper_review_class",
        "_review_progress_status_label",
        "_review_progress_status_class",
        "_review_progress_detail",
    ],
    "command": [
        "dashboard_context",
        "command_summary",
        "command_actions",
        "source_status_rows",
        "readiness_view",
        "data_refresh_progress_view",
        "trade_pull_progress_view",
        "data_load_status_view",
        "full_live_readiness_view",
        "scheduler_work_queue_view",
        "live_config_view",
        "provider_readiness_view",
        "_data_load_row",
        "_data_load_issue",
        "_freshness_status_row",
        "_full_live_command_rows",
        "_optional_int",
        "_optional_mapping",
        "_list_field_or_empty",
        "_data_load_count_label",
        "operational_readiness_view",
        "paper_review_status_context",
        "operational_readiness_context",
        "scheduler_work_queue_status_context",
        "paper_review_status_from_runtime",
        "human_review_events_for_reports",
        "paper_review_queue",
        "paper_review_progress",
        "_risk_decision_index",
        "_source_status_class",
        "_readiness_status_class",
        "_readiness_blocker_rows",
        "_provider_readiness_row",
        "_command_hero_class",
        "_command_headline",
        "_command_detail",
        "policy_sections",
        "policy_summary",
    ],
}

# Per-module top-level imports actually needed (trimmed from the original
# dashboard import block). Modules not listed get the minimal stdlib set.
# We instead compute imports dynamically; see build_imports().

STDLIB_IMPORTS = {
    "asyncio": "import asyncio",
    "os": "import os",
    "re": "import re",
    "Counter": "from collections import Counter",
    "Mapping": "from collections.abc import Mapping, Sequence",
    "Sequence": "from collections.abc import Mapping, Sequence",
    "UTC": "from datetime import UTC, datetime",
    "datetime": "from datetime import UTC, datetime",
    "Path": "from pathlib import Path",
    "monotonic": "from time import monotonic",
    "Any": "from typing import Any, cast",
    "cast": "from typing import Any, cast",
    "urlencode": "from urllib.parse import urlencode, urlsplit",
    "urlsplit": "from urllib.parse import urlencode, urlsplit",
    "pd": "import pandas as pd",
    "load_dotenv": "from dotenv import load_dotenv",
    "HTTPException": "from fastapi import HTTPException",
    "SQLAlchemyError": "from sqlalchemy.exc import SQLAlchemyError",
}

# third-party / agency imports keyed by the name they provide
AGENCY_IMPORTS = {
    "runtime_portfolio_snapshots": "from agency.api.audit import runtime_portfolio_snapshots",
    "RuntimeCandidateTimelineUnavailable": "from agency.api.candidates import RuntimeCandidateTimelineUnavailable, runtime_candidate_timeline",
    "runtime_candidate_timeline": "from agency.api.candidates import RuntimeCandidateTimelineUnavailable, runtime_candidate_timeline",
    "contract_summaries": "from agency.api.health import contract_summaries, runtime_data_source_status",
    "runtime_data_source_status": "from agency.api.health import contract_summaries, runtime_data_source_status",
    "RuntimeSelectionReportsUnavailable": "from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports",
    "runtime_selection_reports": "from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports",
    "RuntimeRiskDecisionsUnavailable": "from agency.api.risk import RuntimeRiskDecisionsUnavailable, runtime_risk_decisions",
    "runtime_risk_decisions": "from agency.api.risk import RuntimeRiskDecisionsUnavailable, runtime_risk_decisions",
    "AlpacaBrokerClient": "from agency.broker import AlpacaBrokerClient, AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot, build_market_order_payload",
    "AlpacaBrokerError": "from agency.broker import AlpacaBrokerClient, AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot, build_market_order_payload",
    "AlpacaTradingConfig": "from agency.broker import AlpacaBrokerClient, AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot, build_market_order_payload",
    "broker_snapshot": "from agency.broker import AlpacaBrokerClient, AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot, build_market_order_payload",
    "build_market_order_payload": "from agency.broker import AlpacaBrokerClient, AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot, build_market_order_payload",
    "MissingDatabaseConfigurationError": "from agency.db import MissingDatabaseConfigurationError, get_session",
    "get_session": "from agency.db import MissingDatabaseConfigurationError, get_session",
    "build_live_readiness": "from agency.runtime import build_live_readiness, execution_freshness_gate, list_candidate_lifecycle_events, record_candidate_lifecycle_event, scheduler_work_queue_context",
    "execution_freshness_gate": "from agency.runtime import build_live_readiness, execution_freshness_gate, list_candidate_lifecycle_events, record_candidate_lifecycle_event, scheduler_work_queue_context",
    "list_candidate_lifecycle_events": "from agency.runtime import build_live_readiness, execution_freshness_gate, list_candidate_lifecycle_events, record_candidate_lifecycle_event, scheduler_work_queue_context",
    "record_candidate_lifecycle_event": "from agency.runtime import build_live_readiness, execution_freshness_gate, list_candidate_lifecycle_events, record_candidate_lifecycle_event, scheduler_work_queue_context",
    "scheduler_work_queue_context": "from agency.runtime import build_live_readiness, execution_freshness_gate, list_candidate_lifecycle_events, record_candidate_lifecycle_event, scheduler_work_queue_context",
    "load_data_load_status": "from agency.runtime.data_load_status import load_data_load_status",
    "load_data_refresh_progress": "from agency.runtime.data_refresh_progress import load_data_refresh_progress",
    "load_full_live_readiness": "from agency.runtime.full_live_readiness import load_full_live_readiness",
    "load_lane_promotion_status": "from agency.runtime.lane_promotion import load_lane_promotion_status",
    "load_live_config_readiness": "from agency.runtime.live_config_readiness import load_live_config_readiness",
    "load_market_regime_snapshot": "from agency.runtime.market_regime import load_market_regime_snapshot",
    "build_operational_readiness": "from agency.runtime.operational_readiness import build_operational_readiness",
    "load_provider_readiness": "from agency.runtime.provider_readiness import load_provider_readiness",
    "enrich_signal_rows_with_evidence": "from agency.runtime.signal_evidence import enrich_signal_rows_with_evidence",
    "PaperTradePromotionConfig": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "PortfolioPolicy": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_and_persist_human_review_event": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_execution_previews": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_learning_outcome": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_leveraged_alternative_review": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_order_approval_event": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_portfolio_monitor": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "build_risk_decisions": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "persist_order_execution_state": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "persist_portfolio_snapshot": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
    "promote_paper_trade_reports": "from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_and_persist_human_review_event, build_execution_previews, build_learning_outcome, build_leveraged_alternative_review, build_order_approval_event, build_portfolio_monitor, build_risk_decisions, persist_order_execution_state, persist_portfolio_snapshot, promote_paper_trade_reports",
}


def build_function_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for mod, names in MODULES.items():
        for n in names:
            lookup[n] = mod
    return lookup


def extract_function_sources(src_lines: list[str]) -> dict[str, tuple[str, int, int]]:
    src = "".join(src_lines)
    tree = ast.parse(src)
    result: dict[str, tuple[str, int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list)
            end = node.end_lineno
            text = "".join(src_lines[start - 1: end])
            result[node.name] = (text, start, end)
    return result


def extract_constants(src: str) -> dict[str, str]:
    """Return mapping constant name -> source text (full statement)."""
    tree = ast.parse(src)
    src_lines = src.splitlines(keepends=True)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name):
                out[tgt.id] = "".join(src_lines[node.lineno - 1: node.end_lineno])
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = "".join(src_lines[node.lineno - 1: node.end_lineno])
    return out


def find_referenced_names(fn_text: str) -> set[str]:
    try:
        tree = ast.parse(fn_text)
    except SyntaxError:
        return set()
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                refs.add(base.id)
    return refs


def indent_of(fn_text: str) -> str:
    """Body indent for a function (assume 4 spaces)."""
    return "    "


def inject_lazy_imports(fn_text: str, imports_by_mod: dict[str, set[str]]) -> str:
    """Insert lazy import lines at the top of a function body."""
    if not imports_by_mod:
        return fn_text
    lines = fn_text.splitlines(keepends=True)
    # find the def line(s) -> the body starts after the line ending with ':'
    # handle multi-line signatures
    header_end = 0
    depth = 0
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        depth += stripped.count("(") - stripped.count(")")
        if depth <= 0 and stripped.rstrip().endswith(":"):
            header_end = i
            break
    insert_at = header_end + 1
    # skip a docstring if present
    body_first = lines[insert_at].lstrip() if insert_at < len(lines) else ""
    import_lines = []
    for mod in sorted(imports_by_mod):
        names = ", ".join(sorted(imports_by_mod[mod]))
        import_lines.append(f"    from agency.views.{mod} import {names}\n")
    return "".join(lines[:insert_at]) + "".join(import_lines) + "".join(lines[insert_at:])


def build_module(
    mod: str,
    names: list[str],
    funcs: dict[str, tuple[str, int, int]],
    constants: dict[str, str],
    lookup: dict[str, str],
) -> str:
    local = set(names)
    parts: list[str] = []
    parts.append(f'"""View-model constructors for the {mod} page."""\n')
    parts.append("from __future__ import annotations\n\n")

    # Determine which names are referenced across all functions in this module.
    all_refs: set[str] = set()
    for n in names:
        all_refs |= find_referenced_names(funcs[n][0])

    # stdlib + agency imports actually used
    stdlib_lines: set[str] = set()
    agency_lines: set[str] = set()
    for ref in all_refs:
        if ref in STDLIB_IMPORTS:
            stdlib_lines.add(STDLIB_IMPORTS[ref])
        if ref in AGENCY_IMPORTS:
            agency_lines.add(AGENCY_IMPORTS[ref])

    for line in sorted(stdlib_lines):
        parts.append(line + "\n")
    if stdlib_lines:
        parts.append("\n")
    for line in sorted(agency_lines):
        parts.append(line + "\n")
    if agency_lines:
        parts.append("\n")

    # _shared imports (constants + shared functions) at top level
    if mod != "_shared":
        shared_needed: list[str] = []
        for c in SHARED_CONSTANTS:
            if c in all_refs:
                shared_needed.append(c)
        for fn in MODULES["_shared"]:
            if fn in all_refs and fn not in local:
                shared_needed.append(fn)
        if shared_needed:
            parts.append("from agency.views._shared import (\n")
            for name in sorted(set(shared_needed)):
                parts.append(f"    {name},\n")
            parts.append(")\n\n")

    # Module caches
    for cache_name, cache_type in MODULE_CACHES.get(mod, []):
        parts.append(f"{cache_name}: {cache_type} = {{}}\n")
    if MODULE_CACHES.get(mod):
        parts.append("\n")

    # Functions, with lazy cross-module imports injected.
    sorted_names = sorted(names, key=lambda n: funcs[n][1])
    for n in sorted_names:
        text = funcs[n][0]
        refs = find_referenced_names(text)
        # cross-module (non-_shared, non-local) refs -> lazy import
        lazy: dict[str, set[str]] = {}
        for r in refs:
            if r in lookup:
                owner = lookup[r]
                if owner != mod and owner != "_shared":
                    lazy.setdefault(owner, set()).add(r)
        text = inject_lazy_imports(text, lazy)
        parts.append("\n")
        parts.append(text)
        if not text.endswith("\n"):
            parts.append("\n")

    return "".join(parts)


def build_shared_module(
    names: list[str],
    funcs: dict[str, tuple[str, int, int]],
    constants: dict[str, str],
) -> str:
    parts: list[str] = []
    parts.append('"""Shared constants and utility helpers for dashboard view modules."""\n')
    parts.append("from __future__ import annotations\n\n")

    all_refs: set[str] = set()
    for n in names:
        all_refs |= find_referenced_names(funcs[n][0])
    # also constants reference things
    for c in SHARED_CONSTANTS:
        if c in constants:
            all_refs |= find_referenced_names(constants[c])

    stdlib_lines: set[str] = set()
    agency_lines: set[str] = set()
    for ref in all_refs:
        if ref in STDLIB_IMPORTS:
            stdlib_lines.add(STDLIB_IMPORTS[ref])
        if ref in AGENCY_IMPORTS:
            agency_lines.add(AGENCY_IMPORTS[ref])
    for line in sorted(stdlib_lines):
        parts.append(line + "\n")
    if stdlib_lines:
        parts.append("\n")
    for line in sorted(agency_lines):
        parts.append(line + "\n")
    if agency_lines:
        parts.append("\n")

    # constants in original order
    for c in SHARED_CONSTANTS:
        parts.append(constants[c])
    parts.append("\n")

    sorted_names = sorted(names, key=lambda n: funcs[n][1])
    for n in sorted_names:
        text = funcs[n][0]
        parts.append("\n")
        parts.append(text)
        if not text.endswith("\n"):
            parts.append("\n")
    return "".join(parts)


DASHBOARD_HEADER = '''from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from agency.api.health import runtime_data_source_status
from agency.broker import (
    AlpacaBrokerClient,
    AlpacaBrokerError,
    AlpacaTradingConfig,
    build_market_order_payload,
)
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import execution_freshness_gate, record_candidate_lifecycle_event
from agency.runtime.lane_promotion import load_lane_promotion_status
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.services import (
    PortfolioPolicy,
    build_and_persist_human_review_event,
    build_order_approval_event,
    persist_portfolio_snapshot,
)
from agency.views._shared import _env_bool_text, _mapping_field, _optional_float_field

# Route handlers below reference these view-model constructors. Helper symbols
# that are not used directly by routes are still re-exported here so existing
# callers of ``agency.dashboard`` (and tests) keep working after the split.
from agency.views.candidates import (  # noqa: F401
    _candidate_review_redirect_url,
    candidate_decision_brief,
    candidate_detail_context,
    candidate_detail_report_rows,
    candidate_detail_summary,
    candidate_email_evidence,
    candidate_email_evidence_with_judgement,
    candidate_review_summary,
    candidate_rows,
    timeline_rows,
)
from agency.views.command import (  # noqa: F401
    command_summary,
    dashboard_context,
    data_load_status_view,
    data_refresh_progress_view,
    human_review_events_for_reports,
    live_config_view,
    operational_readiness_context,
    paper_review_progress,
    paper_review_queue,
    paper_review_status_context,
    paper_review_status_from_runtime,
    policy_sections,
    policy_summary,
    provider_readiness_view,
    readiness_view,
    scheduler_work_queue_status_context,
    source_status_rows,
)
from agency.views.execution import (  # noqa: F401
    _record_submitted_order,
    execution_preview_context,
    execution_preview_order_row,
    execution_preview_rows,
)
from agency.views.final_selection import (  # noqa: F401
    final_selection_context,
    final_selection_rows,
    final_selection_summary,
)
from agency.views.learning import learning_context, learning_summary  # noqa: F401
from agency.views.market_regime import (  # noqa: F401
    broker_status_context,
    market_regime_context,
)
from agency.views.portfolio import (  # noqa: F401
    portfolio_monitor_context,
    portfolio_monitor_summary,
)
from agency.views.risk import (  # noqa: F401
    risk_context,
    risk_decision_rows,
    risk_summary,
)
from agency.views.signals import (  # noqa: F401
    signal_dashboard_rows,
    signal_dashboard_summary,
    signal_lane_rows,
    signals_context,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
'''


def build_dashboard(funcs: dict[str, tuple[str, int, int]]) -> str:
    parts: list[str] = [DASHBOARD_HEADER]
    for name in ROUTES_STAY:
        text = funcs[name][0]
        parts.append("\n\n")
        parts.append(text.rstrip("\n"))
        parts.append("\n")
    return "".join(parts)


def main() -> None:
    src = DASH.read_text(encoding="utf-8")
    src_lines = src.splitlines(keepends=True)
    funcs = extract_function_sources(src_lines)
    constants = extract_constants(src)
    lookup = build_function_lookup()

    missing = [n for mod in MODULES.values() for n in mod if n not in funcs]
    if missing:
        print("MISSING FUNCS:", missing)
        sys.exit(1)
    missing_c = [c for c in SHARED_CONSTANTS if c not in constants]
    if missing_c:
        print("MISSING CONSTANTS:", missing_c)
        sys.exit(1)

    # Build _shared first
    shared_text = build_shared_module(MODULES["_shared"], funcs, constants)
    (VIEWS / "_shared.py").write_text(shared_text, encoding="utf-8")
    print(f"Wrote _shared.py ({len(MODULES['_shared'])} functions)")

    for mod, names in MODULES.items():
        if mod == "_shared":
            continue
        text = build_module(mod, names, funcs, constants, lookup)
        (VIEWS / f"{mod}.py").write_text(text, encoding="utf-8")
        print(f"Wrote {mod}.py ({len(names)} functions)")

    dashboard_text = build_dashboard(funcs)
    DASH.write_text(dashboard_text, encoding="utf-8")
    print(f"Wrote dashboard.py ({len(ROUTES_STAY)} route handlers)")


if __name__ == "__main__":
    main()
