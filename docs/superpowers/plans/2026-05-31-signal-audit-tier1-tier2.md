# Signal Audit Tier 1 and Tier 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Tier 1 and Tier 2 findings from the 2026-05-31 full signals audit so the Signals dashboard and inspector explain signal strength, score scale, actionability, source limits, and table summaries in investor-readable language.

**Architecture:** Keep the existing signal pipeline intact and improve the view-model, evidence-inspector, and promotion-policy layers. Add one small score-context registry in `src/agency/views/signals.py`, dedicated evidence reconstructors for options lanes in `src/agency/runtime/signal_evidence.py`, and focused tests around every user-visible contract. Correctness-sensitive scoring changes stay in the research signal layer with unit tests before implementation.

**Tech Stack:** Python 3.14, FastAPI/Jinja templates, Pandas/Polars research signals, existing PIT loaders, pytest, Ruff.

---

## Scope

This plan covers Tier 1 and Tier 2 from `Pasted text.txt`:

- F-01 fundamentals period mismatch verification/fix
- INST-01 13F institutional lane cannot be action-weighted
- S-01 and UX-02 score scale/context
- UX-01 generic signal-summary fallback
- S-02 actionability threshold reason
- S-03 neutral-score epsilon explanation
- UX-13 dynamic Signals page summary
- OF-01 and OA-01 options-flow/options-anomaly inspectors
- N-01 keyword-only news limitation note
- ST-01 subscription-thesis scoring quality/depth
- UX-03, UX-05, UX-08, UX-09, UX-10, UX-12 quick label fixes that naturally belong with the above work

New signal coverage from Tier 4 is out of scope.

---

## File Map

| File | Responsibility |
|---|---|
| `research/src/pit/sec_views.py` | Verify/fix fundamentals period alignment so annual and quarterly metrics cannot silently mix. |
| `research/src/signals/fundamentals.py` | Keep fundamentals score inputs aligned and expose enough period metadata for evidence. |
| `research/src/signals/subscription_thesis.py` | Replace fixed thesis score behavior with depth/source/relevance weighted scoring. |
| `src/agency/runtime/lane_promotion.py` | Force `institutional` to context-only and explain 13F reporting delay. |
| `src/agency/runtime/signal_evidence.py` | Add score context, actionability explanation, options inspectors, news limitation, better institutional and fundamentals wording. |
| `src/agency/views/signals.py` | Add score-context fields, lane-specific fallback summaries, dynamic summary text, user-facing lane state labels. |
| `src/agency/templates/signals.html` | Rename UI labels, surface score context/suppression reason, improve lane-card copy. |
| `tests/unit/test_pit_loader.py` | Fundamentals period-alignment regression coverage. |
| `tests/unit/test_signal_evidence.py` | Evidence inspector coverage for options, news, institutional, actionability, score context. |
| `tests/unit/test_fastapi_app.py` | Signals dashboard rows, summary, labels, and rendered HTML coverage. |

---

## Task 1: Fundamentals Period Alignment Guard

**Findings:** F-01

**Files:**
- Modify: `research/src/pit/sec_views.py`
- Modify if needed: `research/src/signals/fundamentals.py`
- Test: `tests/unit/test_pit_loader.py`
- Test: `tests/unit/test_signal_evidence_fundamentals.py`

- [ ] **Step 1: Write a failing period-mismatch regression test**

Add this test to `tests/unit/test_pit_loader.py` near the existing SEC/fundamentals tests:

```python
def test_fundamentals_do_not_mix_quarterly_revenue_with_annual_income() -> None:
    frame = pl.DataFrame(
        [
            {
                "ticker": "MIX",
                "metric": "revenue",
                "value": 100.0,
                "period_end": "2025-03-31",
                "fiscal_period": "Q1",
                "fiscal_year": 2025,
                "form": "10-Q",
                "accession": "q1-revenue",
                "timestamp_as_of": datetime(2025, 4, 25, tzinfo=UTC),
            },
            {
                "ticker": "MIX",
                "metric": "net_income",
                "value": 120.0,
                "period_end": "2024-12-31",
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "form": "10-K",
                "accession": "fy-income",
                "timestamp_as_of": datetime(2025, 2, 15, tzinfo=UTC),
            },
        ]
    )

    payload = sec_views.fundamentals_from_frame(frame, ticker="MIX")

    assert payload["period_alignment_status"] == "incomplete_period"
    assert payload["net_margin"] is None
    assert payload["quality_score_basis"] == "period_aligned_only"
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_pit_loader.py::test_fundamentals_do_not_mix_quarterly_revenue_with_annual_income -q
```

Expected before fix: fail because the payload computes a margin from mismatched periods.

- [ ] **Step 2: Implement one-period metric selection**

In `research/src/pit/sec_views.py`, change fundamentals payload construction so ratio metrics only use rows from one chosen reporting period. Use this helper shape:

```python
def _period_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("fiscal_year") or ""),
        str(row.get("fiscal_period") or ""),
        str(row.get("period_end") or ""),
    )


def _best_aligned_period(rows: Sequence[Mapping[str, object]]) -> tuple[str, str, str] | None:
    by_period: dict[tuple[str, str, str], set[str]] = {}
    for row in rows:
        metric = str(row.get("metric") or "")
        if metric:
            by_period.setdefault(_period_key(row), set()).add(metric)
    required = {"revenue", "net_income"}
    complete = [period for period, metrics in by_period.items() if required <= metrics]
    return max(complete) if complete else None
```

Use the selected period for `revenue`, `net_income`, `operating_cash_flow`, `capital_expenditures`, `free_cash_flow`, `total_assets`, and `total_liabilities` ratio inputs. If no period contains both revenue and net income, set period-derived ratios to `None` and set `period_alignment_status` to `incomplete_period`.

- [ ] **Step 3: Make the evidence wording operator-readable**

In `src/agency/runtime/signal_evidence.py`, replace the fundamentals detail prefix:

```python
f"SEC period alignment is {_text(detail.get('period_alignment_status'), 'unknown')}. "
```

with a helper:

```python
def _fundamentals_period_alignment_sentence(detail: Mapping[str, object]) -> str:
    status = _text(detail.get("period_alignment_status"), "unknown")
    period = _filing_period_label(detail)
    if status == "aligned":
        return f"Using SEC metrics from one aligned reporting period: {period}."
    if status == "incomplete_period":
        return f"SEC metrics for {period} were incomplete, so ratio scores that need matching revenue and income are not used."
    return f"SEC period alignment could not be fully verified for {period}."
```

Use this sentence in `_fundamentals_evidence()`.

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_pit_loader.py tests\unit\test_signal_evidence_fundamentals.py -q
.\.venv\Scripts\python -m ruff check research\src\pit\sec_views.py research\src\signals\fundamentals.py src\agency\runtime\signal_evidence.py tests\unit\test_pit_loader.py tests\unit\test_signal_evidence_fundamentals.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add research/src/pit/sec_views.py research/src/signals/fundamentals.py src/agency/runtime/signal_evidence.py tests/unit/test_pit_loader.py tests/unit/test_signal_evidence_fundamentals.py
git commit -m "Fix fundamentals period alignment"
```

---

## Task 2: Institutional 13F Must Be Context Only

**Findings:** INST-01, INST-02, INST-03

**Files:**
- Modify: `src/agency/runtime/lane_promotion.py`
- Modify: `src/agency/runtime/signal_evidence.py`
- Test: `tests/unit/test_fastapi_app.py`
- Test: `tests/unit/test_signal_evidence.py`

- [ ] **Step 1: Write policy test**

Add to `tests/unit/test_fastapi_app.py`:

```python
def test_institutional_lane_is_context_only_because_13f_is_lagged() -> None:
    status = load_lane_promotion_status(["institutional"])
    row = next(item for item in status["lanes"] if item["lane"] == "institutional")

    assert row["state"] == "context_only"
    assert "45" in row["runtime_effect"]
    assert "lagged" in row["rationale"].lower()
```

Import `load_lane_promotion_status` from `agency.runtime.lane_promotion`.

- [ ] **Step 2: Change promotion policy**

In `src/agency/runtime/lane_promotion.py`, replace the `institutional` policy with:

```python
"institutional": LanePromotionPolicy(
    "institutional",
    CONTEXT_ONLY,
    "Context only: 13F filings are delayed by up to 45 days after quarter end.",
    "SEC 13F manifest available and mapped through the local CUSIP map.",
    (
        "Official 13F data confirms historical institutional positioning, but the "
        "filing delay makes it unsuitable as a current action-weighted signal."
    ),
),
```

- [ ] **Step 3: Remove misleading implied value/share card**

In `_institutional_evidence()` remove the `Implied value/share` card and change:

```python
"Current-basis change"
```

to:

```python
"Position size change"
```

Change the detail to:

```python
"Net shares changed divided by currently reported shares. This measures reported position-size change, not stock-price return."
```

Change the main detail text to:

```python
"13F holdings are delayed quarterly SEC filings, usually available up to 45 days after quarter end. Treat this as historical ownership context, not live institutional flow."
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_institutional_lane_is_context_only_because_13f_is_lagged tests\unit\test_signal_evidence.py::test_institutional_signal_inspector_names_holder_changes_and_ratio_basis -q
.\.venv\Scripts\python -m ruff check src\agency\runtime\lane_promotion.py src\agency\runtime\signal_evidence.py tests\unit\test_fastapi_app.py tests\unit\test_signal_evidence.py
```

Expected: tests pass and no Ruff errors.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/runtime/lane_promotion.py src/agency/runtime/signal_evidence.py tests/unit/test_fastapi_app.py tests/unit/test_signal_evidence.py
git commit -m "Keep 13F institutional signals context only"
```

---

## Task 3: Score Context Registry and Visible Score Meaning

**Findings:** S-01, UX-02, S-03

**Files:**
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/templates/signals.html`
- Modify: `src/agency/runtime/signal_evidence.py`
- Test: `tests/unit/test_fastapi_app.py`
- Test: `tests/unit/test_signal_evidence.py`

- [ ] **Step 1: Write view-model tests**

Add to `tests/unit/test_fastapi_app.py`:

```python
def test_signal_dashboard_rows_explain_score_scale_and_neutral_threshold() -> None:
    selection_rows = final_selection_rows([_selection_report_with_signal_mix()])
    rows = signal_dashboard_rows(selection_rows)
    by_lane = {row["lane_key"]: row for row in rows}

    assert by_lane["technical_analysis"]["score_context_type"] == "absolute_composite"
    assert "technical composite" in by_lane["technical_analysis"]["score_context_detail"].lower()
    assert by_lane["fundamentals"]["score_context_type"] == "fundamental_composite"
    assert "not a percentile" in by_lane["fundamentals"]["score_context_detail"].lower()
    assert "Direction becomes neutral" in by_lane["news"]["direction_threshold_detail"]
```

- [ ] **Step 2: Add score context helpers**

In `src/agency/views/signals.py`, add constants near `_signals_context_cache`:

```python
DIRECTION_EPSILON = 0.05

SCORE_CONTEXT_BY_LANE: dict[str, tuple[str, str, str]] = {
    "abnormal_volume": ("cross_section_rank", "Universe rank", "Cross-sectional rank of signed volume pressure within the current universe; not a conviction percent."),
    "buy_sell_pressure": ("cross_section_rank", "Universe rank", "Cross-sectional rank of signed notional pressure within the current universe."),
    "block_trade_pressure": ("cross_section_rank", "Universe rank", "Cross-sectional rank of large/off-exchange print pressure within the current universe."),
    "unusual_trade_activity": ("cross_section_rank", "Universe rank", "Cross-sectional rank of unusual trade activity pressure within the current universe."),
    "pre_market_unusual_activity": ("cross_section_rank", "Universe rank", "Cross-sectional rank of pre-market activity pressure within the current universe."),
    "market_flow_trend": ("cross_section_rank", "Universe rank", "Cross-sectional rank of rolling market-flow trend pressure within the current universe."),
    "options_flow": ("cross_section_rank", "Universe rank", "Cross-sectional rank of call/put options pressure within the current universe."),
    "options_anomaly": ("cross_section_rank", "Universe rank", "Cross-sectional rank of unusual options premium and volume pressure within the current universe."),
    "technical_analysis": ("absolute_composite", "Technical composite", "Absolute weighted technical composite from trend, momentum, volume, relative strength, pattern, trade pressure, and volatility risk."),
    "fundamentals": ("fundamental_composite", "Fundamental composite", "Composite of quality, growth, valuation, and forward inputs; not a percentile and not a candidate conviction score."),
    "insider": ("z_score", "Universe z-score", "Standard-deviation score for net insider transaction value versus the current universe."),
    "institutional": ("z_score", "Universe z-score", "Standard-deviation score for lagged 13F position change versus the current universe; context only because filings are delayed."),
    "news": ("z_score", "Universe z-score", "Standard-deviation score for keyword news sentiment versus the current universe."),
    "sector_momentum": ("z_score", "Universe z-score", "Standard-deviation score for sector momentum versus recent sector baseline."),
    "prepost": ("z_score", "Universe z-score", "Standard-deviation score for extended-hours gap and volume pressure."),
    "subscription_thesis": ("thesis_weighted", "Weighted thesis score", "Signed subscription article score weighted by article confidence, source quality, relevance, and recency."),
}
```

Add helper:

```python
def _score_context_fields(signal: Mapping[str, object]) -> dict[str, str]:
    lane = str(signal["lane"])
    score_type, short, detail = SCORE_CONTEXT_BY_LANE.get(
        lane,
        ("lane_score", "Lane score", "Lane-specific score. Open the inspector for source details."),
    )
    score = _float_field(signal, "score")
    if abs(score) <= DIRECTION_EPSILON:
        threshold = (
            f"Direction becomes neutral when score is between -{DIRECTION_EPSILON:.2f} "
            f"and +{DIRECTION_EPSILON:.2f}; current score is {score:+.2f}."
        )
    else:
        threshold = (
            f"Direction is assigned when score is outside -{DIRECTION_EPSILON:.2f} "
            f"to +{DIRECTION_EPSILON:.2f}; current score is {score:+.2f}."
        )
    return {
        "score_context_type": score_type,
        "score_context_label": short,
        "score_context_detail": detail,
        "direction_threshold_detail": threshold,
    }
```

In `_signal_rows()`, merge this helper into every row:

```python
row = {...}
row.update(_score_context_fields(signal))
rows.append(row)
```

- [ ] **Step 3: Surface context in template**

In `src/agency/templates/signals.html`, replace the score cell:

```jinja2
<td data-label="Score">{{ row.score }}</td>
```

with:

```jinja2
<td data-label="Score">
  <span title="{{ row.score_context_detail }}">{{ row.score }}</span>
  <small class="cell-note">{{ row.score_context_label }}</small>
</td>
```

In the inspector facts panel, add:

```jinja2
<div>
  <span class="metric-label">Score Meaning</span>
  <p>{{ row.score_context_detail }}</p>
  <p>{{ row.direction_threshold_detail }}</p>
</div>
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signal_dashboard_rows_explain_score_scale_and_neutral_threshold -q
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signal_dashboard_rows_group_sort_and_summarize_lanes -q
.\.venv\Scripts\python -m ruff check src\agency\views\signals.py src\agency\templates\signals.html tests\unit\test_fastapi_app.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/signals.py src/agency/templates/signals.html tests/unit/test_fastapi_app.py
git commit -m "Explain signal score scale"
```

---

## Task 4: Replace Generic Signal Summary Fallback

**Findings:** UX-01, UX-04

**Files:**
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/runtime/signal_evidence.py`
- Test: `tests/unit/test_fastapi_app.py`
- Test: `tests/unit/test_signal_evidence.py`

- [ ] **Step 1: Write summary fallback tests**

Add to `tests/unit/test_fastapi_app.py`:

```python
def test_signal_summary_fallback_never_repeats_lane_and_direction_only() -> None:
    signal = {
        "lane": "technical_analysis",
        "direction": "BULLISH",
        "score": 0.62,
        "reason_codes": ["technical_analysis_bullish"],
    }

    summary = signals_module._signal_summary(signal)

    assert "no lane summary was persisted" not in summary
    assert "Technical Analysis: direction bullish" not in summary
    assert "technical setup" in summary.lower()
```

Add a second test:

```python
def test_enriched_signal_row_uses_trigger_headline_as_table_summary() -> None:
    row = enrich_signal_rows_with_evidence(
        [_signal_row("abnormal_volume", "Abnormal Volume")],
        loader=FakePriceLoader(),
    )[0]

    assert row["summary"].startswith("AAPL triggered abnormal volume")
    assert "no lane summary was persisted" not in row["summary"]
```

- [ ] **Step 2: Add lane fallback summaries**

In `src/agency/views/signals.py`, replace the final return in `_signal_summary()` with:

```python
return _generated_signal_summary(signal)
```

Add:

```python
def _generated_signal_summary(signal: Mapping[str, object]) -> str:
    lane = str(signal["lane"])
    direction = _label_text(str(signal.get("direction") or "UNKNOWN")).lower()
    score = _score_text(signal)
    reason = _signal_reason_text(signal)
    templates = {
        "abnormal_volume": f"Volume anomaly is {direction}; score {score}. {reason}",
        "technical_analysis": f"Technical setup is {direction}; score {score}. {reason}",
        "fundamentals": f"Fundamentals read as {direction}; score {score}. {reason}",
        "insider": f"Insider Form 4 flow is {direction}; score {score}. {reason}",
        "institutional": f"Lagged 13F ownership context is {direction}; score {score}. {reason}",
        "news": f"Keyword news context is {direction}; score {score}. {reason}",
        "subscription_thesis": f"Subscription article thesis is {direction}; score {score}. {reason}",
        "options_flow": f"Options flow context is {direction}; score {score}. {reason}",
        "options_anomaly": f"Options anomaly context is {direction}; score {score}. {reason}",
    }
    return _clip_text(templates.get(lane, f"{_label_text(lane)} is {direction}; score {score}. {reason}"), 220)
```

- [ ] **Step 3: Let rich inspector headline upgrade table summary**

In `_apply_concrete_inspection_text()` in `src/agency/runtime/signal_evidence.py`, add:

```python
if headline:
    row["summary"] = _clip_sentence(headline, max_chars=220)
```

If `_clip_sentence` currently accepts only one argument, replace it with:

```python
def _clip_sentence(value: str, *, max_chars: int = 180) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signal_summary_fallback_never_repeats_lane_and_direction_only tests\unit\test_signal_evidence.py::test_enriched_signal_row_uses_trigger_headline_as_table_summary -q
.\.venv\Scripts\python -m ruff check src\agency\views\signals.py src\agency\runtime\signal_evidence.py tests\unit\test_fastapi_app.py tests\unit\test_signal_evidence.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/signals.py src/agency/runtime/signal_evidence.py tests/unit/test_fastapi_app.py tests/unit/test_signal_evidence.py
git commit -m "Generate concrete signal row summaries"
```

---

## Task 5: Actionability and Suppression Reasons

**Findings:** S-02, UX-05

**Files:**
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/templates/signals.html`
- Modify: `src/agency/runtime/signal_evidence.py`
- Test: `tests/unit/test_fastapi_app.py`

- [ ] **Step 1: Add tests**

Add to `tests/unit/test_fastapi_app.py`:

```python
def test_context_signal_explains_why_it_did_not_drive_decision() -> None:
    selection_rows = final_selection_rows([_selection_report_with_signal_mix()])
    row = next(item for item in signal_dashboard_rows(selection_rows) if item["bucket"] == "Context")

    assert row["treatment_reason_label"]
    assert "threshold" in row["treatment_reason_detail"].lower() or "confidence" in row["treatment_reason_detail"].lower()
```

- [ ] **Step 2: Add treatment explanation helper**

In `src/agency/views/signals.py`, add:

```python
ACTIONABILITY_SCORE_THRESHOLD = 0.50
ACTIONABILITY_CONFIDENCE_THRESHOLD = 50


def _treatment_reason_fields(signal: Mapping[str, object]) -> dict[str, str]:
    actionability = str(signal["actionability"])
    score = abs(_float_field(signal, "score"))
    confidence = _percent(signal, "confidence")
    reason = _signal_reason_text(signal)
    if actionability == "ACTIONABLE":
        return {
            "treatment_reason_label": "Used in score",
            "treatment_reason_detail": "This signal passed the score and confidence gates for its lane.",
        }
    if score < ACTIONABILITY_SCORE_THRESHOLD:
        return {
            "treatment_reason_label": "Score below gate",
            "treatment_reason_detail": f"Absolute score {score:.2f} is below the actionability threshold of {ACTIONABILITY_SCORE_THRESHOLD:.2f}. {reason}",
        }
    if confidence < ACTIONABILITY_CONFIDENCE_THRESHOLD:
        return {
            "treatment_reason_label": "Confidence below gate",
            "treatment_reason_detail": f"Confidence {confidence}% is below the {ACTIONABILITY_CONFIDENCE_THRESHOLD}% minimum. {reason}",
        }
    return {
        "treatment_reason_label": "Policy guarded",
        "treatment_reason_detail": reason,
    }
```

Merge the helper into each `_signal_rows()` row.

- [ ] **Step 3: Surface it in table and inspector**

In `signals.html`, change the treatment cell to:

```jinja2
<td data-label="Treatment">
  <span class="tag tag-{{ row.bucket_class }}">{{ row.bucket }}</span>
  {% if row.bucket != "Actionable" %}
  <small class="cell-note" title="{{ row.treatment_reason_detail }}">{{ row.treatment_reason_label }}</small>
  {% endif %}
</td>
```

In the facts panel, add:

```jinja2
<div>
  <span class="metric-label">Why This Role</span>
  <p>{{ row.treatment_reason_detail }}</p>
</div>
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_context_signal_explains_why_it_did_not_drive_decision -q
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signal_dashboard_rows_group_sort_and_summarize_lanes -q
.\.venv\Scripts\python -m ruff check src\agency\views\signals.py src\agency\templates\signals.html tests\unit\test_fastapi_app.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/signals.py src/agency/templates/signals.html tests/unit/test_fastapi_app.py
git commit -m "Show signal treatment reasons"
```

---

## Task 6: Dynamic Signals Page Summary

**Findings:** UX-13, UX-14

**Files:**
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/templates/signals.html`
- Test: `tests/unit/test_fastapi_app.py`

- [ ] **Step 1: Add summary tests**

Add to `tests/unit/test_fastapi_app.py`:

```python
def test_signal_dashboard_summary_names_top_signal_and_direction_distribution() -> None:
    rows = signal_dashboard_rows(final_selection_rows([_selection_report_with_signal_mix()]))
    lane_rows = signal_lane_rows(rows, {"lanes": [_promotion_lane("fundamentals", "action_weighted")]})

    summary = signal_dashboard_summary(
        signal_rows=rows,
        lane_rows=lane_rows,
        cycle_id="live-pit-current",
        report_count=1,
    )

    assert "1 actionable signal" in summary["detail"]
    assert "Strongest:" in summary["detail"]
    assert "bullish" in summary["detail"].lower()
    assert summary["actionable_description"] == "Included in the final conviction score"
    assert summary["context_description"] == "Explains context but does not add to the score"
    assert summary["suppressed_description"] == "Recorded for audit but excluded from scoring"
```

- [ ] **Step 2: Add summary detail helper**

In `src/agency/views/signals.py`, replace the static `detail` assignment with:

```python
detail = _signals_summary_detail(
    signal_rows,
    report_count=report_count,
    actionable_count=actionable_count,
    context_count=context_count,
    suppressed_count=suppressed_count,
    bullish_count=bullish_count,
    bearish_count=bearish_count,
)
```

Add:

```python
def _signals_summary_detail(
    signal_rows: Sequence[Mapping[str, object]],
    *,
    report_count: int,
    actionable_count: int,
    context_count: int,
    suppressed_count: int,
    bullish_count: int,
    bearish_count: int,
) -> str:
    neutral_count = len(signal_rows) - bullish_count - bearish_count
    distribution = f"{bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral"
    if signal_rows:
        top = sorted(signal_rows, key=lambda row: -abs(_float_field(row, "score_value")))[0]
        strongest = (
            f"Strongest: {top['display_name']} for {top['ticker']} "
            f"({top['score']})."
        )
    else:
        strongest = "No signal has enough current evidence to rank yet."
    return (
        f"{actionable_count} actionable signal(s), {context_count} context signal(s), "
        f"and {suppressed_count} suppressed signal(s) across {report_count} selection report(s). "
        f"{distribution}. {strongest}"
    )
```

Add these fields to the return dict:

```python
"actionable_description": "Included in the final conviction score",
"context_description": "Explains context but does not add to the score",
"suppressed_description": "Recorded for audit but excluded from scoring",
```

- [ ] **Step 3: Use descriptions in KPI grid**

In `signals.html`, replace:

```jinja2
<p>can drive decisions</p>
<p>explains but guarded</p>
<p>ignored or too weak</p>
```

with:

```jinja2
<p>{{ summary.actionable_description }}</p>
<p>{{ summary.context_description }}</p>
<p>{{ summary.suppressed_description }}</p>
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signal_dashboard_summary_names_top_signal_and_direction_distribution -q
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signal_dashboard_rows_group_sort_and_summarize_lanes -q
.\.venv\Scripts\python -m ruff check src\agency\views\signals.py src\agency\templates\signals.html tests\unit\test_fastapi_app.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/signals.py src/agency/templates/signals.html tests/unit/test_fastapi_app.py
git commit -m "Make signals summary state specific"
```

---

## Task 7: Options Flow and Options Anomaly Inspectors

**Findings:** OF-01, OF-02, OA-01

**Files:**
- Modify: `src/agency/runtime/signal_evidence.py`
- Test: `tests/unit/test_signal_evidence.py`

- [ ] **Step 1: Add tests for options flow**

Add to `tests/unit/test_signal_evidence.py` a fake loader method:

```python
class FakeOptionsLoader(FakePriceLoader):
    def option_chains(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {"ticker": "AAPL", "snapshot_date": as_of.isoformat(), "option_type": "call", "volume": 500, "open_interest": 1000, "implied_volatility": 0.45, "bid": 2.0, "ask": 2.2, "last_price": 2.1, "timestamp_as_of": AS_OF},
                {"ticker": "AAPL", "snapshot_date": as_of.isoformat(), "option_type": "put", "volume": 100, "open_interest": 900, "implied_volatility": 0.42, "bid": 1.0, "ask": 1.2, "last_price": 1.1, "timestamp_as_of": AS_OF},
            ]
        )
```

Add:

```python
def test_options_flow_inspector_reconstructs_call_put_metrics() -> None:
    row = enrich_signal_rows_with_evidence(
        [_signal_row("options_flow", "Options Flow")],
        loader=FakeOptionsLoader(),
    )[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}

    assert "call volume" in row["trigger_headline"].lower()
    assert labels["Call volume"]["value"] == "500"
    assert labels["Put volume"]["value"] == "100"
    assert labels["Put/call volume ratio"]["value"] == "0.20"
```

- [ ] **Step 2: Add tests for options anomaly**

Add:

```python
def test_options_anomaly_inspector_reconstructs_premium_and_oi_metrics() -> None:
    row = enrich_signal_rows_with_evidence(
        [_signal_row("options_anomaly", "Options Anomaly")],
        loader=FakeOptionsLoader(),
    )[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}

    assert "option premium" in row["trigger_headline"].lower()
    assert labels["Call premium"]["value"].startswith("$")
    assert labels["Put premium"]["value"].startswith("$")
    assert "volume divided by open interest" in labels["Volume/OI"]["detail"]
```

- [ ] **Step 3: Load options frames**

In `src/agency/runtime/signal_evidence.py`, import:

```python
from signals.options_anomaly import options_anomaly_frame
from signals.options_flow import options_flow_frame
```

In `_detail_frames()`, add:

```python
if "options_flow" in lanes:
    frames["options_flow"] = _safe_frame(options_flow_frame, as_of, tickers, loader)
if "options_anomaly" in lanes:
    frames["options_anomaly"] = _safe_frame(options_anomaly_frame, as_of, tickers, loader)
```

Add builders:

```python
"options_flow": _options_flow_evidence,
"options_anomaly": _options_anomaly_evidence,
```

- [ ] **Step 4: Implement `_options_flow_evidence()`**

Add:

```python
def _options_flow_evidence(row: Mapping[str, object], detail: Mapping[str, object], as_of: date) -> dict[str, object]:
    headline = (
        f"{row['ticker']} options flow used call volume {_integer(detail.get('call_volume'))} "
        f"versus put volume {_integer(detail.get('put_volume'))}; put/call volume ratio "
        f"{_plain_number(detail.get('put_call_volume_ratio'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "This reconstructs the latest option-chain snapshot. Call-heavy volume is bullish context; "
            "put-heavy volume is bearish context. The lane remains disabled unless a real options provider is configured."
        ),
        cards=[
            _card("Call volume", _integer(detail.get("call_volume")), "Total call contract volume in the latest snapshot."),
            _card("Put volume", _integer(detail.get("put_volume")), "Total put contract volume in the latest snapshot."),
            _card("Put/call volume ratio", _plain_number(detail.get("put_call_volume_ratio")), "Put volume divided by call volume; above 1.0 means puts traded more than calls."),
            _card("Call share", _unsigned_pct(detail.get("call_share")), "Call volume divided by total option volume."),
            _card("Open interest", _integer(detail.get("open_interest")), "Total open interest across contracts in the snapshot."),
            _card("Mean IV", _unsigned_pct(detail.get("mean_implied_volatility")), "Average implied volatility for contracts with IV values."),
            _card("Options pressure", _number(detail.get("options_pressure")), "Signed call/put pressure before universe ranking."),
            _card("Options score", _number(detail.get("options_flow_score")), "Universe rank score for options flow pressure."),
        ],
    )
```

- [ ] **Step 5: Implement `_options_anomaly_evidence()`**

Add:

```python
def _options_anomaly_evidence(row: Mapping[str, object], detail: Mapping[str, object], as_of: date) -> dict[str, object]:
    headline = (
        f"{row['ticker']} options anomaly detected gross option premium "
        f"{_money(detail.get('gross_premium'))}, net premium {_money(detail.get('net_premium'))}, "
        f"and volume/OI {_plain_number(detail.get('volume_to_open_interest'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "This reconstructs unusual option activity from premium, volume, and open interest. "
            "Positive net premium means call-side premium dominated; negative means put-side premium dominated."
        ),
        cards=[
            _card("Call premium", _money(detail.get("call_premium")), "Estimated call premium: contract price times volume times 100."),
            _card("Put premium", _money(detail.get("put_premium")), "Estimated put premium: contract price times volume times 100."),
            _card("Net premium", _money(detail.get("net_premium")), "Call premium minus put premium.", _money_tone(detail.get("net_premium"))),
            _card("Gross premium", _money(detail.get("gross_premium")), "Call premium plus put premium."),
            _card("Option volume", _integer(detail.get("total_option_volume")), "Total contracts traded in the latest snapshot."),
            _card("Open interest", _integer(detail.get("total_open_interest")), "Total open interest across contracts."),
            _card("Volume/OI", _plain_number(detail.get("volume_to_open_interest")), "Total option volume divided by open interest; high values indicate unusual activity."),
            _card("Unusual contracts", _integer(detail.get("unusual_contract_count")), "Contracts with volume at least 100 and volume/open-interest at least 2.0, or no open interest."),
            _card("Anomaly score", _number(detail.get("options_anomaly_score")), "Universe rank score for unusual options pressure."),
        ],
    )
```

- [ ] **Step 6: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_signal_evidence.py::test_options_flow_inspector_reconstructs_call_put_metrics tests\unit\test_signal_evidence.py::test_options_anomaly_inspector_reconstructs_premium_and_oi_metrics -q
.\.venv\Scripts\python -m ruff check src\agency\runtime\signal_evidence.py tests\unit\test_signal_evidence.py
```

- [ ] **Step 7: Commit**

```powershell
git add src/agency/runtime/signal_evidence.py tests/unit/test_signal_evidence.py
git commit -m "Add options signal inspectors"
```

---

## Task 8: News Methodology Limitation and Subscription Thesis Scoring

**Findings:** N-01, ST-01

**Files:**
- Modify: `src/agency/runtime/signal_evidence.py`
- Modify: `research/src/signals/subscription_thesis.py`
- Test: `tests/unit/test_signal_evidence.py`
- Test: `tests/unit/test_subscription_thesis.py` if present, otherwise create it.

- [ ] **Step 1: Add news inspector test**

Add to `tests/unit/test_signal_evidence.py`:

```python
def test_news_inspector_states_keyword_methodology_limit() -> None:
    row = enrich_signal_rows_with_evidence(
        [_signal_row("news", "News")],
        loader=FakeNewsLoader(),
    )[0]

    assert "keyword" in row["trigger_detail"].lower()
    assert "not full article llm sentiment" in row["trigger_detail"].lower()
```

- [ ] **Step 2: Update news detail**

In `_news_evidence()`, append:

```python
"This is keyword taxonomy, not full article LLM sentiment, so it should be treated as low-conviction context unless corroborated."
```

to the detail string.

- [ ] **Step 3: Add subscription scoring tests**

Create `tests/unit/test_subscription_thesis.py` if it does not exist:

```python
from __future__ import annotations

from datetime import date

from signals.subscription_thesis import subscription_thesis_contexts


class Loader:
    def subscription_emails(self, tickers: list[str], as_of: date, lookback_days: int) -> list[dict[str, object]]:
        return [
            {
                "ticker": "ASML",
                "linked_content_status": "article_analyzed",
                "linked_content_summary": "Linked content thesis: direct bullish thesis.",
                "linked_content_direction": "BULLISH",
                "linked_content_relevance": "direct",
                "source_quality": "premium_article",
                "confidence": 0.80,
                "timestamp_as_of": "2026-05-30T12:00:00+00:00",
            },
            {
                "ticker": "ASML",
                "linked_content_status": "article_analyzed",
                "linked_content_summary": "Linked content thesis: weak secondary mention.",
                "linked_content_direction": "BULLISH",
                "linked_content_relevance": "secondary",
                "source_quality": "headline_only",
                "confidence": 0.80,
                "timestamp_as_of": "2026-05-29T12:00:00+00:00",
            },
        ]


def test_subscription_thesis_score_weights_relevance_and_source_depth() -> None:
    contexts = subscription_thesis_contexts(date(2026, 5, 31), {"ASML"}, Loader())

    assert len(contexts) == 1
    assert 0.30 < contexts[0].score < 0.65
    assert "direct" in contexts[0].summary
```

- [ ] **Step 4: Implement source/depth weighting**

In `research/src/signals/subscription_thesis.py`, add:

```python
SOURCE_QUALITY_WEIGHTS = {
    "premium_article": 1.0,
    "full_article": 1.0,
    "article": 0.9,
    "email_summary": 0.65,
    "headline_only": 0.35,
}
RELEVANCE_WEIGHTS = {
    "direct": 1.0,
    "primary": 1.0,
    "secondary": 0.55,
    "sector": 0.35,
    "macro": 0.25,
}


def _source_quality_weight(event: dict[str, object]) -> float:
    key = str(event.get("source_quality") or event.get("linked_content_depth") or "").lower()
    return SOURCE_QUALITY_WEIGHTS.get(key, 0.75)


def _relevance_weight(event: dict[str, object]) -> float:
    key = str(event.get("linked_content_relevance") or event.get("ticker_relevance") or "").lower()
    return RELEVANCE_WEIGHTS.get(key, 0.75)
```

In `_context()`, replace:

```python
scores = [_direction_score(event) * _confidence(event) for event in ordered]
weights = [RECENCY_DECAY**index for index, _event in enumerate(ordered)]
```

with:

```python
scores = [_direction_score(event) * _confidence(event) for event in ordered]
weights = [
    (RECENCY_DECAY**index) * _source_quality_weight(event) * _relevance_weight(event)
    for index, event in enumerate(ordered)
]
```

- [ ] **Step 5: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_signal_evidence.py::test_news_inspector_states_keyword_methodology_limit tests\unit\test_subscription_thesis.py -q
.\.venv\Scripts\python -m ruff check src\agency\runtime\signal_evidence.py research\src\signals\subscription_thesis.py tests\unit\test_signal_evidence.py tests\unit\test_subscription_thesis.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/agency/runtime/signal_evidence.py research/src/signals/subscription_thesis.py tests/unit/test_signal_evidence.py tests/unit/test_subscription_thesis.py
git commit -m "Clarify news and weight subscription thesis"
```

---

## Task 9: Signals UX Label Cleanup

**Findings:** UX-03, UX-08, UX-09, UX-10, UX-12

**Files:**
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/templates/signals.html`
- Test: `tests/unit/test_fastapi_app.py`

- [ ] **Step 1: Add rendered-label test**

Add to `tests/unit/test_fastapi_app.py`:

```python
def test_signals_template_uses_operator_labels_not_internal_jargon() -> None:
    html = (PROJECT_ROOT / "src/agency/templates/signals.html").read_text(encoding="utf-8")

    assert ">Bucket<" not in html
    assert ">Muted<" not in html
    assert "Signal Pipelines" in html
    assert "Role in Decision" in html
    assert "Signal Quality" in html
    assert "Data Source" in html
```

- [ ] **Step 2: Add state display helper**

In `src/agency/views/signals.py`, add:

```python
LANE_STATE_DISPLAY = {
    "action_weighted": "Drives decisions",
    "corroborating": "Supports context",
    "context_only": "Context only",
    "disabled": "Disabled",
}
```

In `_signal_lane_row()`, replace:

```python
"state_label": _label_text(state),
```

with:

```python
"state_label": LANE_STATE_DISPLAY.get(state, _label_text(state)),
```

- [ ] **Step 3: Rename labels in template**

In `signals.html`, make these exact label replacements:

```text
Signal Data Health -> Signal Pipelines
Bucket -> Treatment
Muted -> Suppressed
Actionability -> Role in Decision
Quality -> Signal Quality
Reason Codes -> Why This Was Classified
Reason Meaning -> What This Means
Provenance -> Data Source
Current Candidate -> Candidate State
```

Update matching `data-label` values for the table cells.

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_signals_template_uses_operator_labels_not_internal_jargon tests\unit\test_fastapi_app.py::test_signal_dashboard_rows_group_sort_and_summarize_lanes -q
.\.venv\Scripts\python -m ruff check src\agency\views\signals.py tests\unit\test_fastapi_app.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/signals.py src/agency/templates/signals.html tests/unit/test_fastapi_app.py
git commit -m "Clean up signals dashboard labels"
```

---

## Final Verification

After all tasks are complete, run:

```powershell
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pytest tests\unit\test_signal_evidence.py tests\unit\test_signal_evidence_fundamentals.py tests\unit\test_fastapi_app.py tests\unit\test_pit_loader.py tests\unit\test_subscription_thesis.py -q
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py
```

Expected:

- Ruff exits 0.
- Targeted pytest suite exits 0.
- Runtime smoke reports `health: ok`, at least 1 selection report, and at least 1 risk decision.
- Cockpit UX QA reports `failure_count=0`.

Then push:

```powershell
git status --short --branch
git push origin feat/ux-product-audit-20260529
git ls-remote origin refs/heads/feat/ux-product-audit-20260529
```

Expected:

- Working tree is clean.
- Remote branch hash matches local `git rev-parse HEAD`.

---

## Self-Review

- Spec coverage: Tier 1 and Tier 2 findings are mapped to Tasks 1-9. Tier 4 new signals are intentionally out of scope.
- Placeholder scan: no task uses an undefined future placeholder; every test and code step names concrete files and functions.
- Type consistency: all new fields are plain strings added to existing signal row dictionaries and consumed by Jinja templates.
