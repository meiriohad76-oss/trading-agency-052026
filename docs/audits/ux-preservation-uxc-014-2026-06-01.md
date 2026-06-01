# UXC-014 Preservation Regression Harness

- Status: **PASS**
- Ticket: UXC-014
- Started: 2026-06-01T19:02:07.198977+00:00
- Finished: 2026-06-01T19:02:48.619204+00:00
- Groups: signals, fundamentals, subscription, cockpit, process, institutional

## Definition Of Done

One command gives clear preservation PASS/FAIL and identifies the protected behavior that changed.

## Protected Checks

- PASS [candidate] candidate ranking remains conviction-sorted - top three tickers were ['RICH', 'TRF', 'EMAIL']
- PASS [candidate] candidate evidence keeps concrete hard values - Price closed +4.2% while daily volume ran 2.8x the 30-day median.
- PASS [candidate] focused execution route keeps selected ticker - /execution-preview?ticker=RICH#focused-preview-RICH
- PASS [candidate] candidate actionability and controls stay tied to order readiness - {'actionable': True, 'status': 'approved', 'decision_controls': ['order'], 'order_preview': '$4,200'}
- PASS [candidate] candidate keeps deterministic and LLM score fields - {'det_conviction': 0.91, 'llm_conviction': 0.83, 'llm_label': 'LLM agrees', 'evidence_tiers': ['confirmed']}
- PASS [candidate] manual LLM wording is preserved outside top 10 - LLM not run because this ticker is outside the top 10 automatic review set.
- PASS [lane-state] operator wording does not expose stale jargon - data_state text is sanitized
- PASS [lane-state] live lane exposes individual scheduler refresh action - {'url': '/scheduler/massive-lanes/massive_live_trade_slices/refresh', 'label': 'Refresh Live Trade Slices', 'detail': "Runs this data source through the scheduler's trade-aware policy."}
- PASS [lane-state] subscription lane uses login refresh action - {'url': '/scheduler/subscription-emails/login-refresh', 'label': 'Open Seeking Alpha login refresh', 'detail': 'Opens regular installed Chrome for the login-gated email/article refresh flow.'}
- PASS [lane-state] optional disabled lane is not presented as a blocker - {'lane_id': 'massive_options_flow', 'name': 'Massive Options Flow', 'lane_kind_label': 'raw_acquisition', 'state': 'disabled_optional', 'status_label': 'Not required for current workflow', 'status_class': 'neutral', 'progress_label': 'not tracked', 'progress_percent': None, 'eta_label': 'not reported', 'required_now': False, 'required_label': 'Optional today', 'blocks_execution': False, 'blocks_paper_label': 'No', 'blocker': False, 'ready_for_review': False, 'ready_for_paper_execution': False, 'latest_as_of_label': 'not recorded', 'checked_at_label': '2026-06-01T18:35:30+00:00', 'refresh_action': {'url': '', 'label': 'Policy locked', 'detail': 'Refresh Options Flow is tracked for health, but this data source is not exposed as a runnable scheduler refresh in the current policy.'}, 'requirement_label': 'Direct source', 'operator_message': 'Options flow is optional for the current workflow.', 'recommended_action': 'No action needed today; Massive Options Flow is not required for the current workflow.', 'gap_detail': 'Options flow is optional for the current workflow.', 'tooltip': 'Massive Options Flow: Not required for current workflow. Progress: not tracked. Proof: not recorded. Next action: No action needed today; Massive Options Flow is not required for the current workflow.', 'sort_key': 90}
- PASS [candidate-detail] detail drawer preserves TRF/off-exchange hard evidence - TRF/off-exchange 4 / $440.0M; Directional read +72.0% buy-side; Confidence 86% | Most unusual metric Notional and share volume; Notional anomaly 4.0x; Confidence 78%
- PASS [candidate-detail] detail drawer preserves subscription email context - [{"detail": "Two Seeking Alpha articles were mapped to RICH with bullish thesis confidence.", "label": "Subscription email", "meta": "Email evidence synced", "tone": "pass"}, {"detail": "Generic RSS headline was resolved to RICH and marked consumed.", "label": "News/RSS", "meta": "RSS evidence resolved", "tone": "pass"}]
- PASS [candidate-detail] email evidence fixture carries article judgement contract - {'meaning': 'Email evidence synced', 'detail': 'Two Seeking Alpha articles were mapped to RICH with bullish thesis confidence.', 'status_class': 'pass', 'linked_content_status': 'article_analyzed', 'article_count': 2, 'decision_use': 'Treat as context-only bullish thesis until corroborated by market data.', 'judgement_contribution': 'Supports the current RICH Buy judgment because article thesis, price action, and flow pressure agree.', 'local_llm_article_status': 'completed', 'local_llm_article_direction': 'BULLISH', 'local_llm_article_confidence': 0.82}
- PASS [candidate-detail] manual LLM action remains available when report timestamp exists - {'status_label': 'LLM agrees', 'status_detail': '', 'action': 'AGREE', 'confidence_pct': 83, 'rationale': 'LLM agrees because price, flow, and subscription evidence corroborate.', 'manual_review_available': True, 'manual_review_action': '/candidates/RICH/llm-review', 'manual_review_detail': 'Automatic LLM review is limited to the top 10 ranked candidates. This runs the same reviewer for the selected ticker and report timestamp.'}
- PASS [signal-evidence] fundamentals explain trend and user meaning - Using SEC metrics from one aligned reporting period: Q1 2026. Revenue increased 11.0%; net income increased 16.0%; free cash flow increased 21.0% versus the same period last year. The agency treats positive margins and growth as bullish, negative cash generation as bearish, and high leverage as bearish because it leaves less balance-sheet cushion. Forward fundamentals ready.
- PASS [signal-evidence] institutional evidence names holder changes and ratio basis - RICH 13F net change was +2,400,000 shares across 4 tracked holder(s); top changes: Northstar Capital +750,000, Harbor Ridge Advisors +420,000.
- PASS [signal-evidence] block trade evidence explains TRF/off-exchange not venue proof - The signal is bullish because focused block/off-exchange notional was buy-leaning: +$316.80M signed focused notional out of $440.00M focused notional. Focused prints represented 50.0% of all analyzed notional, so the large-print lane treated this as meaningful pressure. TRF/off-exchange means reported through FINRA TRF; it is useful large-print evidence, not proof of a dark-pool venue.
- PASS [signal-evidence] unusual trade evidence identifies what was unusual - RICH identified unusual trade activity: notional was most unusual; trade count 2.20x, notional 4.00x, share volume 3.60x, and detected-period pressure +64.0% buy-leaning.
- PASS [static] production cockpit does not expose window.COCKPIT_DATA - searched 6 production files
- PASS [static] production cockpit does not expose EDITMODE - searched 6 production files
- PASS [static] production cockpit does not expose C-14:32 - searched 6 production files
- PASS [static] production cockpit does not expose grossPostTrade - searched 6 production files
- PASS [static] production cockpit does not expose Health Monitor Fallback - searched 4 production files
- PASS [static] production cockpit does not expose Fallback Thesis - searched 4 production files
- PASS [static] production cockpit does not expose Fallback Analysis - searched 4 production files
- PASS [static] production cockpit does not expose recent mailbox sample - searched 4 production files
- PASS [static] production cockpit does not expose first-version - searched 4 production files
- PASS [static] production cockpit does not expose hidden artifact fallback - searched 6 production files
- PASS [static] production cockpit does not expose artifact_fallback - searched 6 production files

## Pytest Bundles

- PASS [signals] `C:\Users\meiri\trading_agency\.venv\Scripts\python.exe -m pytest -q tests/unit/test_signal_evidence.py tests/unit/test_signal_evidence_fundamentals.py tests/unit/test_market_flow_signals.py tests/unit/test_signal_calibration.py tests/unit/test_signal_adapters.py`
- PASS [fundamentals] `C:\Users\meiri\trading_agency\.venv\Scripts\python.exe -m pytest -q tests/unit/test_signal_evidence_fundamentals.py tests/unit/test_fundamentals_signal.py tests/unit/test_fundamentals_growth.py tests/unit/test_forward_fundamentals_state.py tests/unit/test_sec_views_period_fix.py tests/unit/test_pit_loader.py`
- PASS [subscription] `C:\Users\meiri\trading_agency\.venv\Scripts\python.exe -m pytest -q tests/unit/test_subscription_thesis_signal.py tests/unit/test_subscription_email_agents.py tests/unit/test_portfolio_news_agent_bridge.py tests/unit/test_news_signal.py tests/unit/test_news_ticker_resolution.py tests/unit/test_fastapi_app.py::test_data_load_status_view_exposes_subscription_email_progress tests/unit/test_fastapi_app.py::test_candidate_email_evidence_ties_articles_to_current_judgement tests/unit/test_subscription_email_agents.py::test_visible_browser_session_verifies_first_email_article_before_fetch`
- PASS [cockpit] `C:\Users\meiri\trading_agency\.venv\Scripts\python.exe -m pytest -q tests/unit/test_cockpit_contract.py tests/unit/test_cockpit_candidates.py tests/unit/test_cockpit_lane_state.py tests/unit/test_lane_state.py tests/unit/test_cockpit_no_demo_data.py tests/unit/test_cockpit_routes.py tests/unit/test_cockpit_panels.py`
- PASS [process] `C:\Users\meiri\trading_agency\.venv\Scripts\python.exe -m pytest -q tests/unit/test_cockpit_clearance.py tests/unit/test_cockpit_legacy_reconciliation.py tests/unit/test_dashboard_live_data_qa_script.py tests/unit/test_ops_scripts.py::test_user_process_audit_accepts_focused_execution_contract tests/unit/test_ops_scripts.py::test_user_process_audit_detects_buried_execution_focus`
- PASS [institutional] `C:\Users\meiri\trading_agency\.venv\Scripts\python.exe -m pytest -q tests/unit/test_institutional_signal.py tests/unit/test_signal_evidence.py::test_institutional_signal_inspector_names_holder_changes_and_ratio_basis tests/unit/test_actionability_gate.py::test_actionability_gate_rejects_confirmed_signal_demoted_by_own_lane_gate tests/unit/test_actionability_gate.py::test_actionability_gate_caps_institutional_at_context_only`

## Visual Artifacts

- Screenshots captured: 0
- Prototype compared: No browser screenshot in this preservation command; run check_cockpit_ux_qa for visual prototype comparison.
- Accepted deltas: 0
