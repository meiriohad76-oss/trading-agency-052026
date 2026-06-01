# Signals Quality & Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the top-priority correctness and UX gaps identified in `docs/audits/signals-audit-2026-05-31.md`: cap institutional signals at CONTEXT_ONLY (stale-data correctness), replace generic summary column text with specific evidence, add score-scale context, surface actionability reasons, and make the page-level summary dynamic.

**Architecture:** Four layers are touched — (1) `actionability_gate.py` gets a new per-lane `max_actionability` cap, (2) `signal_evidence.py` overrides the summary field after enrichment, (3) `views/signals.py` adds score-scale and actionability-reason fields to every signal row, (4) `templates/signals.html` displays those new fields. No new files required; all changes extend existing patterns.

**Tech Stack:** Python 3.14, Jinja2 templates, pytest, `agency.services.signal_adapters`, `agency.services.actionability_gate`, `agency.runtime.signal_evidence`, `agency.views.signals`, `agency.views._shared`

---

## File Map

| File | Change |
|---|---|
| `src/agency/services/actionability_gate.py` | Add `max_actionability: str \| None = None` to `LaneActionabilityRule`; enforce it in `_gate_signal`; update `DEFAULT_LANE_RULES["institutional"]` |
| `tests/unit/test_actionability_gate.py` | Add test for `max_actionability` cap |
| `src/agency/runtime/signal_evidence.py` | In `_apply_concrete_inspection_text`, override row `"summary"` with `trigger_headline` |
| `tests/unit/test_signal_evidence.py` | Add test that summary is overridden with headline after enrichment |
| `src/agency/views/_shared.py` | Add `LANE_SCORE_SCALE`, `_score_scale_label()`, `_score_scale_tooltip()` |
| `src/agency/views/signals.py` | Add `score_scale`, `score_scale_tooltip`, `actionability_reason_text` to signal rows; make `signal_dashboard_summary` dynamic |
| `src/agency/templates/signals.html` | Render score scale hint, actionability reason, and dynamic summary |

---

## Task 1 — Cap institutional signals at CONTEXT_ONLY

**Why:** 13F data has a mandatory 45-day filing delay. Classifying institutional signals as ACTIONABLE implies the data is current enough to drive trade decisions — it is not.

**Files:**
- Modify: `src/agency/services/actionability_gate.py`
- Test: `tests/unit/test_actionability_gate.py`

- [ ] **Step 1.1 — Write the failing test**

Add to `tests/unit/test_actionability_gate.py`:

```python
def test_actionability_gate_caps_institutional_at_context_only() -> None:
    """Institutional signals must never reach ACTIONABLE because 13F data is 45+ days stale."""
    signal = build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of=AS_OF,
        lane="institutional",
        score=0.9,
        provenance=_provenance("sec", "13f-q1-2026"),
        confidence=0.95,
    )
    # Signal would be ACTIONABLE without the lane cap
    assert signal["actionability"] == "ACTIONABLE"

    gated = apply_actionability_gate([signal])

    assert gated[0]["actionability"] == "CONTEXT_ONLY"
    assert "13f_data_delayed" in _reason_codes(gated[0])
    validate_contract("signal-result", gated[0])
```

- [ ] **Step 1.2 — Run test to verify it fails**

```
python -m pytest tests/unit/test_actionability_gate.py::test_actionability_gate_caps_institutional_at_context_only -v
```

Expected: `FAILED` — the gated institutional signal is currently ACTIONABLE.

- [ ] **Step 1.3 — Add `max_actionability` to `LaneActionabilityRule`**

In `src/agency/services/actionability_gate.py`, replace the `LaneActionabilityRule` dataclass:

```python
@dataclass(frozen=True)
class LaneActionabilityRule:
    """Per-lane evidence thresholds for v1 actionability."""

    min_sources: int = 1
    min_confirmed_sources: int = 1
    inferred_needs_confirmed_corroboration: bool = True
    max_actionability: str | None = None
    max_actionability_reason: str | None = None
```

- [ ] **Step 1.4 — Enforce the cap in `_gate_signal`**

In `src/agency/services/actionability_gate.py`, inside `_gate_signal`, add cap enforcement **after** the existing freshness and threshold checks (insert after `output["suppression_reason"] = None`):

```python
def _gate_signal(
    signal: Mapping[str, object],
    *,
    index: int,
    duplicate_indexes: set[int],
    stats: Mapping[str, _LaneStats],
    confirmed_directions: set[str],
    config: ActionabilityGateConfig,
) -> dict[str, object]:
    output = dict(signal)
    if index in duplicate_indexes:
        return _reclassify(output, "SUPPRESSED", "duplicate_signal_source")
    if signal["actionability"] == "SUPPRESSED":
        return output

    freshness_action = FRESHNESS_ACTIONABILITY.get(str(signal["freshness"]), "SUPPRESSED")
    if freshness_action != "PASS":
        freshness_reason = (
            "stale_evidence" if freshness_action == "CONTEXT_ONLY" else "source_unavailable"
        )
        return _reclassify(output, freshness_action, freshness_reason)
    if signal["actionability"] != "ACTIONABLE":
        return output

    rule = _rule_for(signal, config)
    lane_stats = stats[str(signal["lane"])]
    reason = _threshold_reason(signal, rule, lane_stats, confirmed_directions)
    if reason is not None:
        return _reclassify(output, "CONTEXT_ONLY", reason)

    # Apply per-lane ceiling — some lanes must never exceed a given actionability level
    if rule.max_actionability is not None:
        ceiling_order = {"ACTIONABLE": 0, "CONTEXT_ONLY": 1, "SUPPRESSED": 2}
        current = str(output["actionability"])
        if ceiling_order.get(current, 0) < ceiling_order.get(rule.max_actionability, 0):
            cap_reason = rule.max_actionability_reason or "lane_max_actionability"
            return _reclassify(output, rule.max_actionability, cap_reason)

    output["suppression_reason"] = None
    return output
```

- [ ] **Step 1.5 — Update `DEFAULT_LANE_RULES` for institutional**

In `src/agency/services/actionability_gate.py`, update the `DEFAULT_LANE_RULES` dict — change the `"institutional"` entry:

```python
DEFAULT_LANE_RULES: Mapping[str, LaneActionabilityRule] = {
    "fundamentals": LaneActionabilityRule(),
    "insider": LaneActionabilityRule(),
    "institutional": LaneActionabilityRule(
        max_actionability="CONTEXT_ONLY",
        max_actionability_reason="13f_data_delayed",
    ),
    "sector_momentum": LaneActionabilityRule(),
    "news": LaneActionabilityRule(min_sources=2, min_confirmed_sources=1),
    "activity_alerts": LaneActionabilityRule(),
    "abnormal_volume": LaneActionabilityRule(min_confirmed_sources=0),
    "technical_analysis": LaneActionabilityRule(min_confirmed_sources=0),
    "block_trade_pressure": LaneActionabilityRule(min_confirmed_sources=0),
    "buy_sell_pressure": LaneActionabilityRule(min_confirmed_sources=0),
    "market_flow_trend": LaneActionabilityRule(min_confirmed_sources=0),
    "pre_market_unusual_activity": LaneActionabilityRule(min_confirmed_sources=0),
    "unusual_trade_activity": LaneActionabilityRule(min_confirmed_sources=0),
    "prepost": LaneActionabilityRule(min_confirmed_sources=0),
    "options_flow": LaneActionabilityRule(min_confirmed_sources=0),
    "options_anomaly": LaneActionabilityRule(min_confirmed_sources=0),
}
```

- [ ] **Step 1.6 — Add `"13f_data_delayed"` to `_reason_summary` in `views/_shared.py`**

In `src/agency/views/_shared.py`, inside the `_reason_summary` function's `summaries` dict, add:

```python
        "13f_data_delayed": (
            "Institutional 13F filings have a mandatory 45-day delay from quarter-end. "
            "This signal is kept as context because the underlying data is structurally stale — "
            "it reflects institutional positions from at least one full quarter ago."
        ),
```

Place it alphabetically between `"duplicate_signal_source"` and `"fundamentals_bullish"`.

- [ ] **Step 1.7 — Run the new test to verify it passes**

```
python -m pytest tests/unit/test_actionability_gate.py::test_actionability_gate_caps_institutional_at_context_only -v
```

Expected: `PASSED`

- [ ] **Step 1.8 — Run full gate test suite to verify no regressions**

```
python -m pytest tests/unit/test_actionability_gate.py -v
```

Expected: all tests pass.

- [ ] **Step 1.9 — Commit**

```
git add src/agency/services/actionability_gate.py src/agency/views/_shared.py tests/unit/test_actionability_gate.py
git commit -m "fix(signals): cap institutional lane at CONTEXT_ONLY — 13F data is 45+ days stale

Adds LaneActionabilityRule.max_actionability/max_actionability_reason and
applies it to the institutional lane with reason 13f_data_delayed.
Adds human-readable explanation to _reason_summary."
```

---

## Task 2 — Override generic summary with trigger headline after enrichment

**Why:** The Summary column currently shows `"{lane}: direction {direction}; no lane summary was persisted"` — generic text that adds no information beyond adjacent columns. After enrichment runs, `trigger_headline` contains a specific, concrete, ticker-level description. Use that.

**Files:**
- Modify: `src/agency/runtime/signal_evidence.py`
- Test: `tests/unit/test_signal_evidence.py`

- [ ] **Step 2.1 — Write the failing test**

Add to `tests/unit/test_signal_evidence.py`:

```python
def test_signal_inspector_overrides_generic_summary_with_trigger_headline() -> None:
    """After enrichment, the summary field must contain the trigger_headline, not generic text."""
    rows = [
        _signal_row(
            ticker="AAPL",
            lane="abnormal_volume",
            summary="Abnormal Volume: direction bullish; no lane summary was persisted for this row.",
        )
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakePriceLoader())

    assert len(enriched) == 1
    row = enriched[0]
    assert "no lane summary was persisted" not in row["summary"]
    assert "AAPL" in row["summary"]
    assert len(row["summary"]) > 0
```

Where `_signal_row` is a helper already in that test file (check existing helpers; if there is no `_signal_row` helper, add one matching the pattern used by existing tests):

```python
def _signal_row(
    *,
    ticker: str,
    lane: str,
    summary: str = "",
    direction: str = "BULLISH",
    score: float = 0.75,
    score_value: float = 0.75,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "lane": lane,
        "lane_key": lane,
        "display_name": lane.replace("_", " ").title(),
        "cycle_id": "cycle-1",
        "signal_as_of": "2026-05-08T09:30:00Z",
        "direction": direction,
        "direction_class": "pass",
        "actionability": "ACTIONABLE",
        "actionability_label": "Actionable",
        "actionability_class": "pass",
        "freshness": "FRESH",
        "freshness_class": "pass",
        "verification_level": "CONFIRMED",
        "verification_label": "Confirmed",
        "source_tier": "tier_1",
        "confidence_pct": 90,
        "score": f"+{score:.2f}",
        "score_value": score_value,
        "summary": summary,
        "source": "Test source",
        "source_key": "test",
        "source_id": "test-id-1",
        "timestamp_as_of": "2026-05-08T09:30:00Z",
        "timestamp_label": "2026-05-08 09:30 UTC",
        "signal_as_of_label": "2026-05-08 09:30 UTC",
        "reason_text": "",
        "reason_codes_label": "Abnormal Volume Bullish",
        "interpretation_text": "",
        "decision_effect_text": "",
        "decision_alignment_text": "",
        "quality_text": "",
        "provenance_text": "",
        "report_action": "WATCH",
        "report_conviction_pct": 74,
        "report_gate_status": "PASS",
        "bucket": "Actionable",
        "bucket_class": "pass",
        "candidate_href": f"/candidates/{ticker}",
    }
```

- [ ] **Step 2.2 — Run test to verify it fails**

```
python -m pytest tests/unit/test_signal_evidence.py::test_signal_inspector_overrides_generic_summary_with_trigger_headline -v
```

Expected: `FAILED` — the summary still contains "no lane summary was persisted".

- [ ] **Step 2.3 — Update `_apply_concrete_inspection_text` to override summary**

In `src/agency/runtime/signal_evidence.py`, inside `_apply_concrete_inspection_text`, add the summary override **after** setting `row["interpretation_text"]`:

```python
def _apply_concrete_inspection_text(row: dict[str, object]) -> None:
    headline = _text(row.get("trigger_headline"), "")
    if not headline:
        return
    ticker = _text(row.get("ticker"), "ticker").upper()
    lane = _text(row.get("lane") or row.get("display_name"), "Signal")
    direction = _text(row.get("direction"), "UNKNOWN").lower()
    score = _text(row.get("score"), "no score")
    detail = _text(row.get("trigger_detail"), "")
    concise_detail = f" {_clip_sentence(detail)}" if detail else ""
    row["interpretation_text"] = (
        f"{lane} hard evidence for {ticker}: {headline}{concise_detail} "
        f"Direction is {direction}; score {score}."
    )
    # Override the generic fallback summary with the specific trigger headline.
    # The headline is always concrete (e.g. "AAPL triggered abnormal volume because
    # latest volume was 5x the median...") so it is a strict improvement over
    # "{lane}: direction {direction}; no lane summary was persisted for this row."
    row["summary"] = _clip_sentence(headline, limit=220)

    row["decision_effect_text"] = _concrete_decision_effect_text(row, headline)
    row["quality_text"] = _concrete_quality_text(row)
    if "provenance_text" in row:
        row["provenance_text"] = _concrete_provenance_text(row)
```

- [ ] **Step 2.4 — Run the new test to verify it passes**

```
python -m pytest tests/unit/test_signal_evidence.py::test_signal_inspector_overrides_generic_summary_with_trigger_headline -v
```

Expected: `PASSED`

- [ ] **Step 2.5 — Run full signal_evidence test suite**

```
python -m pytest tests/unit/test_signal_evidence.py tests/unit/test_signal_evidence_fundamentals.py -v
```

Expected: all tests pass.

- [ ] **Step 2.6 — Commit**

```
git add src/agency/runtime/signal_evidence.py tests/unit/test_signal_evidence.py
git commit -m "fix(signals): override generic summary with trigger_headline after enrichment

After evidence enrichment, the summary field now contains the specific
trigger_headline (e.g. 'AAPL triggered abnormal volume because latest
volume was 5x the median...') instead of the generic fallback text."
```

---

## Task 3 — Add score scale label to every signal row

**Why (S-01):** A score of "+0.72" means "72nd-percentile universe rank" for abnormal_volume but "0.72 standard deviations" for insider. Without a label, cross-lane score comparison is meaningless. Users need to know what scale they're looking at.

**Files:**
- Modify: `src/agency/views/_shared.py`
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/templates/signals.html`

- [ ] **Step 3.1 — Add `LANE_SCORE_SCALE` and helpers to `_shared.py`**

In `src/agency/views/_shared.py`, add the following near the other constants at the top of the file (after the existing `DEGRADED_FRESHNESS` or similar blocks):

```python
# Maps each lane key to its score normalization method.
# Used by the dashboard to show users what scale a score is on.
LANE_SCORE_SCALE: dict[str, str] = {
    "abnormal_volume": "universe-rank",
    "technical_analysis": "composite",
    "fundamentals": "composite",
    "insider": "z-score",
    "institutional": "z-score",
    "news": "z-score",
    "buy_sell_pressure": "universe-rank",
    "block_trade_pressure": "universe-rank",
    "unusual_trade_activity": "universe-rank",
    "pre_market_unusual_activity": "universe-rank",
    "market_flow_trend": "universe-rank",
    "subscription_thesis": "direction-tier",
    "options_flow": "universe-rank",
    "options_anomaly": "universe-rank",
    "prepost": "stored",
    "sector_momentum": "z-score",
    "activity_alerts": "stored",
}

_SCORE_SCALE_DISPLAY: dict[str, tuple[str, str]] = {
    "universe-rank": (
        "rank",
        "Cross-section rank: ±1.0 is the highest/lowest in today's universe. "
        "Score magnitude shows where this ticker ranks relative to all others today.",
    ),
    "composite": (
        "composite",
        "Composite score: weighted sum of sub-factors. Positive means net bullish "
        "evidence; negative means net bearish. Not bounded to ±1.0.",
    ),
    "z-score": (
        "z-score",
        "Universe z-score: standard deviations from the universe mean. "
        "±2.0 is significant; ±0.5 is close to average.",
    ),
    "direction-tier": (
        "tier",
        "Direction tier: a fixed value assigned by the source system (+0.65 bullish, "
        "−0.65 bearish, 0.0 neutral). Not a measured confidence.",
    ),
    "stored": (
        "stored",
        "Stored score: preserved from the upstream system that produced this signal row. "
        "Interpretation depends on the source.",
    ),
}


def _score_scale_label(lane_key: str) -> str:
    scale = LANE_SCORE_SCALE.get(lane_key, "stored")
    return _SCORE_SCALE_DISPLAY.get(scale, _SCORE_SCALE_DISPLAY["stored"])[0]


def _score_scale_tooltip(lane_key: str) -> str:
    scale = LANE_SCORE_SCALE.get(lane_key, "stored")
    return _SCORE_SCALE_DISPLAY.get(scale, _SCORE_SCALE_DISPLAY["stored"])[1]
```

- [ ] **Step 3.2 — Write a test for the new helpers**

Add to `tests/unit/test_signals_common.py` (or create a new file `tests/unit/test_signal_view_helpers.py` if no suitable file exists):

```python
from agency.views._shared import _score_scale_label, _score_scale_tooltip


def test_score_scale_label_returns_rank_for_abnormal_volume() -> None:
    assert _score_scale_label("abnormal_volume") == "rank"


def test_score_scale_label_returns_zscore_for_insider() -> None:
    assert _score_scale_label("insider") == "z-score"


def test_score_scale_label_returns_tier_for_subscription_thesis() -> None:
    assert _score_scale_label("subscription_thesis") == "tier"


def test_score_scale_label_returns_stored_for_unknown_lane() -> None:
    assert _score_scale_label("totally_unknown_lane") == "stored"


def test_score_scale_tooltip_is_nonempty_for_all_known_lanes() -> None:
    from agency.views._shared import LANE_SCORE_SCALE
    for lane in LANE_SCORE_SCALE:
        tooltip = _score_scale_tooltip(lane)
        assert len(tooltip) > 20, f"tooltip too short for lane {lane!r}: {tooltip!r}"
```

- [ ] **Step 3.3 — Run the test to verify it passes**

```
python -m pytest tests/unit/test_signals_common.py -v
```

Expected: new tests pass; pre-existing tests unaffected.

- [ ] **Step 3.4 — Add `_score_scale_label` and `_score_scale_tooltip` to the imports in `signals.py`**

In `src/agency/views/signals.py`, add `_score_scale_label` and `_score_scale_tooltip` to the `from agency.views._shared import (...)` block.

- [ ] **Step 3.5 — Add `score_scale` and `score_scale_tooltip` to `_signal_rows`**

In `src/agency/views/signals.py`, inside `_signal_rows`, add two new fields to each row dict (after the existing `"score_value"` entry):

```python
"score_scale": _score_scale_label(lane_key),
"score_scale_tooltip": _score_scale_tooltip(lane_key),
```

- [ ] **Step 3.6 — Add `score_scale` and `score_scale_tooltip` to `signal_dashboard_rows`**

In `src/agency/views/signals.py`, inside `signal_dashboard_rows`, the row is built from the raw signal and then `row.update(_signal_inspection_fields(row, report))`. The `lane_key` is available as `str(signal.get("lane") or "")`. After the `row.update(...)` call, add:

```python
row["score_scale"] = _score_scale_label(str(signal.get("lane") or ""))
row["score_scale_tooltip"] = _score_scale_tooltip(str(signal.get("lane") or ""))
```

Actually look at the function closely — the row is built with `row = dict(signal)` and then `row.update({...})` and `row.update(_signal_inspection_fields(...))`. The lane key is in `str(row.get("lane") or "")`. Add the scale fields at the end of the inner update block:

```python
row.update(
    {
        "ticker": str(report["ticker"]),
        "candidate_href": f"/candidates/{report['ticker']}",
        "report_action": str(report["action"]),
        "report_conviction_pct": _int_field(report, "conviction_pct"),
        "report_gate_status": str(report["gate_status"]),
        "bucket": _signal_bucket_label(key),
        "bucket_class": _signal_bucket_class(key),
        "score_scale": _score_scale_label(str(row.get("lane") or "")),
        "score_scale_tooltip": _score_scale_tooltip(str(row.get("lane") or "")),
    }
)
```

- [ ] **Step 3.7 — Render score scale in `signals.html`**

In `src/agency/templates/signals.html`, update the Score `<td>` in the signal table to add the scale hint:

```html
<td data-label="Score">
  {{ row.score }}
  <small class="score-scale-hint" title="{{ row.score_scale_tooltip }}">({{ row.score_scale }})</small>
</td>
```

- [ ] **Step 3.8 — Run the signal adapter tests to confirm no regressions**

```
python -m pytest tests/unit/test_signal_adapters.py tests/unit/test_signal_evidence.py -v
```

Expected: all tests pass.

- [ ] **Step 3.9 — Commit**

```
git add src/agency/views/_shared.py src/agency/views/signals.py src/agency/templates/signals.html tests/unit/test_signals_common.py
git commit -m "feat(signals): add score scale label to signal table rows

Each signal row now carries score_scale and score_scale_tooltip fields
based on the lane's normalization method (universe-rank, z-score,
composite, direction-tier, stored). Displayed as a small hint next to
the score in the table."
```

---

## Task 4 — Surface actionability classification reason in inspector

**Why (S-02):** A signal with score +0.48 shows as "Context Only" with no explanation. A signal with 40% confidence also shows as "Context Only" — for a different reason. The inspector already has a facts panel; adding a reason sentence costs zero clicks and removes a major source of confusion.

**Files:**
- Modify: `src/agency/views/signals.py`
- Modify: `src/agency/templates/signals.html`

- [ ] **Step 4.1 — Add `_actionability_reason_text` to `signals.py`**

In `src/agency/views/signals.py`, add this function (place it near the other `_signal_*` helper functions):

```python
def _actionability_reason_text(row: Mapping[str, object]) -> str:
    """Plain-English explanation of why a signal has its current actionability classification."""
    actionability = str(row.get("actionability") or "")
    score_value = _float_field(row, "score_value")
    confidence_pct = _int_field(row, "confidence_pct")
    suppression_reason = str(row.get("suppression_reason") or "")

    if actionability == "ACTIONABLE":
        return (
            f"Score {row.get('score', 'n/a')} meets the ±0.50 threshold and "
            f"confidence {confidence_pct}% meets the 50% minimum — "
            "this signal contributes directly to the candidate conviction score."
        )
    if actionability == "CONTEXT_ONLY":
        if suppression_reason:
            return _reason_summary(suppression_reason)
        if abs(score_value) < 0.5:
            return (
                f"Score {row.get('score', 'n/a')} is below the ±0.50 actionability "
                "threshold. The signal explains context but does not drive the conviction score."
            )
        if confidence_pct < 50:
            return (
                f"Confidence {confidence_pct}% is below the 50% minimum. "
                "The signal is kept as context because source confidence is too low "
                "to drive decisions directly."
            )
        return (
            "Signal contributes context but does not meet all actionability gates for this lane."
        )
    if actionability == "SUPPRESSED":
        if suppression_reason:
            return _reason_summary(suppression_reason)
        return "Signal is excluded from decision scoring — see reason code for details."
    return "Signal actionability was not computed."
```

- [ ] **Step 4.2 — Wire `actionability_reason_text` into `_signal_inspection_fields`**

In `src/agency/views/signals.py`, update `_signal_inspection_fields` to include the new field:

```python
def _signal_inspection_fields(
    row: Mapping[str, object],
    report: Mapping[str, object],
) -> dict[str, str]:
    return {
        "interpretation_text": _signal_interpretation_text(row, report),
        "decision_effect_text": _signal_decision_effect_text(row, report),
        "decision_alignment_text": _signal_decision_alignment_text(row, report),
        "quality_text": _signal_quality_text(row),
        "provenance_text": _signal_provenance_text(row),
        "actionability_reason_text": _actionability_reason_text(row),
    }
```

- [ ] **Step 4.3 — Write a test for `_actionability_reason_text`**

Add to `tests/unit/test_signals_common.py` (or the view helpers test file from Task 3):

```python
from agency.views.signals import _actionability_reason_text


def test_actionability_reason_text_actionable() -> None:
    row = {
        "actionability": "ACTIONABLE",
        "score": "+0.72",
        "score_value": 0.72,
        "confidence_pct": 90,
        "suppression_reason": None,
    }
    text = _actionability_reason_text(row)
    assert "±0.50" in text or "±0.50" in text
    assert "conviction score" in text


def test_actionability_reason_text_context_only_low_score() -> None:
    row = {
        "actionability": "CONTEXT_ONLY",
        "score": "+0.38",
        "score_value": 0.38,
        "confidence_pct": 90,
        "suppression_reason": None,
    }
    text = _actionability_reason_text(row)
    assert "below" in text
    assert "0.50" in text


def test_actionability_reason_text_context_only_low_confidence() -> None:
    row = {
        "actionability": "CONTEXT_ONLY",
        "score": "+0.80",
        "score_value": 0.80,
        "confidence_pct": 35,
        "suppression_reason": None,
    }
    text = _actionability_reason_text(row)
    assert "35%" in text
    assert "confidence" in text.lower()


def test_actionability_reason_text_suppressed_with_reason() -> None:
    row = {
        "actionability": "SUPPRESSED",
        "score": "+0.10",
        "score_value": 0.10,
        "confidence_pct": 40,
        "suppression_reason": "13f_data_delayed",
    }
    text = _actionability_reason_text(row)
    assert "45-day" in text or "stale" in text.lower()


def test_actionability_reason_text_suppressed_without_reason() -> None:
    row = {
        "actionability": "SUPPRESSED",
        "score": "+0.10",
        "score_value": 0.10,
        "confidence_pct": 40,
        "suppression_reason": None,
    }
    text = _actionability_reason_text(row)
    assert len(text) > 0
```

- [ ] **Step 4.4 — Run the tests**

```
python -m pytest tests/unit/test_signals_common.py -v
```

Expected: all new tests pass.

- [ ] **Step 4.5 — Render `actionability_reason_text` in the inspector facts panel**

In `src/agency/templates/signals.html`, update the "Actionability" block inside `signal-inspector-facts` to add the reason:

```html
<div>
  <span class="metric-label">Actionability</span>
  <strong class="tag tag-{{ row.actionability_class }}">{{ row.actionability_label }}</strong>
  <p class="muted-line">{{ row.actionability_reason_text }}</p>
</div>
```

- [ ] **Step 4.6 — Run the full test suite for affected files**

```
python -m pytest tests/unit/test_signals_common.py tests/unit/test_signal_evidence.py tests/unit/test_signal_adapters.py -v
```

Expected: all pass.

- [ ] **Step 4.7 — Commit**

```
git add src/agency/views/signals.py src/agency/templates/signals.html tests/unit/test_signals_common.py
git commit -m "feat(signals): surface actionability classification reason in inspector

Adds _actionability_reason_text() that explains in plain English why a
signal is ACTIONABLE, CONTEXT_ONLY, or SUPPRESSED. Shown under the
Actionability badge in the inspector facts panel."
```

---

## Task 5 — Make the page-level summary dynamic

**Why (UX-13):** The current `detail` text reads the same every cycle: "Latest-cycle signal audit across X selection report(s). Use this page to check…" — it describes the page, not the state. When strong actionable signals exist, the summary should name them.

**Files:**
- Modify: `src/agency/views/signals.py`

- [ ] **Step 5.1 — Write a test for dynamic summary behavior**

Add to `tests/unit/test_signals_common.py`:

```python
from agency.views.signals import signal_dashboard_summary


def _make_signal_row(
    bucket: str = "Actionable",
    direction: str = "BULLISH",
    ticker: str = "AAPL",
    lane: str = "Technical Analysis",
    score: str = "+0.82",
    score_value: float = 0.82,
    summary: str = "AAPL technical setup is bullish breakout.",
) -> dict[str, object]:
    return {
        "bucket": bucket,
        "direction": direction,
        "ticker": ticker,
        "lane": lane,
        "score": score,
        "score_value": score_value,
        "summary": summary,
    }


def test_signal_dashboard_summary_names_top_actionable_signal() -> None:
    signal_rows = [
        _make_signal_row(ticker="NVDA", score="+0.92", score_value=0.92, summary="NVDA volume spike."),
        _make_signal_row(ticker="AAPL", score="+0.72", score_value=0.72),
    ]
    result = signal_dashboard_summary(
        signal_rows=signal_rows,
        lane_rows=[],
        cycle_id="cycle-1",
        report_count=2,
        evidence_currentness={"is_current": True, "display_mode": "current"},
    )
    assert "NVDA" in result["detail"] or "NVDA" in result["headline"]


def test_signal_dashboard_summary_reports_no_actionable_when_all_suppressed() -> None:
    signal_rows = [
        _make_signal_row(bucket="Suppressed", direction="BULLISH"),
        _make_signal_row(bucket="Context", direction="BEARISH"),
    ]
    result = signal_dashboard_summary(
        signal_rows=signal_rows,
        lane_rows=[],
        cycle_id="cycle-1",
        report_count=2,
        evidence_currentness={"is_current": True, "display_mode": "current"},
    )
    assert result["actionable_count"] == 0
    assert "no actionable" in result["detail"].lower() or "0 actionable" in result["detail"].lower()
```

- [ ] **Step 5.2 — Run to verify the second test fails (no-actionable case)**

```
python -m pytest "tests/unit/test_signals_common.py::test_signal_dashboard_summary_reports_no_actionable_when_all_suppressed" -v
```

Expected: `FAILED` — current detail text doesn't contain "no actionable".

- [ ] **Step 5.3 — Update `signal_dashboard_summary` to generate dynamic detail**

In `src/agency/views/signals.py`, replace the `detail` and `headline` assignments inside `signal_dashboard_summary`:

```python
def signal_dashboard_summary(
    *,
    signal_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
    cycle_id: str | None,
    report_count: int,
    visible_signal_count: int | None = None,
    previous_signal_count: int = 0,
    evidence_currentness: Mapping[str, object] | None = None,
) -> dict[str, object]:
    visible = len(signal_rows) if visible_signal_count is None else visible_signal_count
    currentness = evidence_currentness or {"is_current": True, "display_mode": "current"}
    is_current = currentness.get("is_current") is True
    actionable_count = sum(1 for row in signal_rows if row["bucket"] == "Actionable")
    context_count = sum(1 for row in signal_rows if row["bucket"] == "Context")
    suppressed_count = sum(1 for row in signal_rows if row["bucket"] == "Suppressed")
    bullish_count = sum(1 for row in signal_rows if row["direction"] == "BULLISH")
    bearish_count = sum(1 for row in signal_rows if row["direction"] == "BEARISH")
    lanes_with_data = sum(1 for row in lane_rows if _int_field(row, "signal_count") > 0)
    configured_lanes = sum(1 for row in lane_rows if row["configured"] is True)
    headline = _signals_headline(len(signal_rows), lanes_with_data)
    detail = _signals_dynamic_detail(
        signal_rows=signal_rows,
        actionable_count=actionable_count,
        bullish_count=bullish_count,
        bearish_count=bearish_count,
        report_count=report_count,
    )
    topbar_label = f"{len(signal_rows)} signals / {lanes_with_data} active lanes"
    if not is_current:
        headline = "Signal analysis is still running; previous-cycle rows are hidden."
        detail = (
            f"{currentness.get('reason') or 'Current evidence is not ready yet'} "
            f"{previous_signal_count} previous persisted signal row(s) are not shown as current."
        )
        topbar_label = f"{currentness.get('status_label') or 'Evidence not current'}"
    return {
        "cycle_id": cycle_id or "None",
        "cycle_label": _short_cycle_label(cycle_id),
        "topbar_label": topbar_label,
        "headline": headline,
        "detail": detail,
        "signal_count": len(signal_rows),
        "previous_signal_count": previous_signal_count,
        "display_mode": str(currentness.get("display_mode") or "current"),
        "visible_signal_count": visible,
        "render_limit": SIGNALS_RENDER_LIMIT,
        "is_limited": visible < len(signal_rows),
        "render_label": (
            f"Showing {visible} highest-priority row(s) out of {len(signal_rows)}"
            if visible < len(signal_rows)
            else f"Showing all {len(signal_rows)} row(s)"
        ),
        "report_count": report_count,
        "lane_count": len(lane_rows),
        "lanes_with_data": lanes_with_data,
        "configured_lanes": configured_lanes,
        "actionable_count": actionable_count,
        "context_count": context_count,
        "suppressed_count": suppressed_count,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
    }
```

- [ ] **Step 5.4 — Add `_signals_dynamic_detail` helper**

In `src/agency/views/signals.py`, add the following function near `_signals_headline`:

```python
def _signals_dynamic_detail(
    *,
    signal_rows: Sequence[Mapping[str, object]],
    actionable_count: int,
    bullish_count: int,
    bearish_count: int,
    report_count: int,
) -> str:
    if not signal_rows:
        return (
            f"No signal rows are available for this cycle across {report_count} "
            "selection report(s). Check data health above."
        )
    total = len(signal_rows)
    direction_summary = (
        f"{bullish_count} bullish, {bearish_count} bearish"
        if bullish_count + bearish_count > 0
        else "no directional signals"
    )
    if actionable_count == 0:
        return (
            f"No actionable signals this cycle — all {total} row(s) are context-only or "
            f"suppressed ({direction_summary}). Review data health and lane states above."
        )
    actionable_rows = [row for row in signal_rows if row["bucket"] == "Actionable"]
    top = max(actionable_rows, key=lambda r: abs(_float_field(r, "score_value")), default=None)
    if top is None:
        return (
            f"{actionable_count} actionable signal(s) across {report_count} "
            f"selection report(s) ({direction_summary})."
        )
    top_ticker = str(top.get("ticker") or "")
    top_lane = str(top.get("lane") or "")
    top_score = str(top.get("score") or "")
    top_direction = str(top.get("direction") or "").lower()
    return (
        f"{actionable_count} actionable signal(s) across {report_count} selection report(s) "
        f"({direction_summary}). "
        f"Strongest: {top_lane} for {top_ticker} ({top_direction}, score {top_score})."
    )
```

- [ ] **Step 5.5 — Run the failing test to verify it now passes**

```
python -m pytest "tests/unit/test_signals_common.py::test_signal_dashboard_summary_reports_no_actionable_when_all_suppressed" "tests/unit/test_signals_common.py::test_signal_dashboard_summary_names_top_actionable_signal" -v
```

Expected: both pass.

- [ ] **Step 5.6 — Run the full test suite for signals**

```
python -m pytest tests/unit/test_signals_common.py tests/unit/test_signal_adapters.py tests/unit/test_signal_evidence.py tests/unit/test_actionability_gate.py -v
```

Expected: all pass.

- [ ] **Step 5.7 — Commit**

```
git add src/agency/views/signals.py tests/unit/test_signals_common.py
git commit -m "feat(signals): dynamic page summary shows actionable count and top signal

signal_dashboard_summary now generates a detail line that names the
strongest actionable signal (ticker, lane, direction, score) when signals
exist, and clearly states 'no actionable signals' when all rows are
context or suppressed."
```

---

## Task 6 — Label consistency cleanup in the template

**Why (UX-03, UX-10, UX-12, UX-14):** Several labels use internal terminology or are inconsistent between the table and the inspector: "Bucket" (column header), "Muted" (lane card counter), state tag values (`action_weighted`, `corroborating`), and KPI descriptions.

**Files:**
- Modify: `src/agency/templates/signals.html`
- Modify: `src/agency/views/signals.py`

These are template-only or view-layer label changes with no behaviour change — no dedicated test is needed; existing tests will catch broken template variable names.

- [ ] **Step 6.1 — Rename "Bucket" column to "Treatment"**

In `src/agency/templates/signals.html`, find:

```html
<th>Bucket</th>
```

Replace with:

```html
<th title="Whether this signal drives decisions, provides context, or is excluded from scoring.">Treatment</th>
```

Also update the `data-label` in the row `<td>` (there are two: one in the summary row, one in responsive):

```html
<td data-label="Treatment"><span class="tag tag-{{ row.bucket_class }}">{{ row.bucket }}</span></td>
```

- [ ] **Step 6.2 — Update KPI descriptions**

In `src/agency/templates/signals.html`, update the three KPI `<p>` descriptions:

Current:
```html
<p>can drive decisions</p>
...
<p>explains but guarded</p>
...
<p>ignored or too weak</p>
```

Replace with:

```html
<p>included in conviction score</p>
...
<p>explains context, not scored</p>
...
<p>excluded from scoring</p>
```

- [ ] **Step 6.3 — Fix "Muted" counter in lane cards to "Suppressed"**

In `src/agency/templates/signals.html`, find:

```html
<div>
  <span class="metric-label">Muted</span>
  <strong>{{ lane.suppressed_count }}</strong>
</div>
```

Replace with:

```html
<div>
  <span class="metric-label">Suppressed</span>
  <strong>{{ lane.suppressed_count }}</strong>
</div>
```

- [ ] **Step 6.4 — Update state tag display values via `_lane_state_display_label`**

The lane card `state_label` comes from `_label_text(state)` in `signals.py`. Add a specific mapping for the lane states in `_signal_lane_row`:

In `src/agency/views/signals.py`, in `_signal_lane_row`, replace:

```python
"state_label": _label_text(state),
```

With:

```python
"state_label": _lane_state_display_label(state),
```

And add the helper near the other `_lane_state_*` functions:

```python
def _lane_state_display_label(state: str) -> str:
    labels = {
        "action_weighted": "Drives decisions",
        "corroborating": "Context only",
        "disabled": "Disabled",
    }
    return labels.get(state, _label_text(state))
```

- [ ] **Step 6.5 — Update section heading from "Signal Data Health" to "Signal Pipelines"**

In `src/agency/templates/signals.html`, find:

```html
<h2 id="lane-heading">Signal Data Health</h2>
```

Replace with:

```html
<h2 id="lane-heading">Signal Pipelines</h2>
```

And update the subtitle to be clearer:

```html
<p class="section-subtitle">
  {{ summary.configured_lanes }} active pipeline(s), {{ summary.lanes_with_data }} with data this cycle.
</p>
```

- [ ] **Step 6.6 — Run the full test suite to verify no regressions**

```
python -m pytest tests/unit/test_signals_common.py tests/unit/test_signal_adapters.py tests/unit/test_signal_evidence.py tests/unit/test_actionability_gate.py -v
```

Expected: all pass.

- [ ] **Step 6.7 — Commit**

```
git add src/agency/templates/signals.html src/agency/views/signals.py
git commit -m "fix(signals): label consistency cleanup — Treatment, Suppressed, state labels

- 'Bucket' column header → 'Treatment' with tooltip
- KPI descriptions: plain English (included in conviction score, etc.)
- 'Muted' lane card counter → 'Suppressed' (consistent with table)
- Lane state tags: action_weighted → 'Drives decisions', corroborating → 'Context only'
- Section heading 'Signal Data Health' → 'Signal Pipelines'"
```

---

## Self-Review

### Spec coverage check

| Audit Finding | Task | Status |
|---|---|---|
| INST-01: Institutional must not be ACTIONABLE | Task 1 | ✅ Covered |
| UX-01: Generic summary fallback | Task 2 | ✅ Covered |
| S-01: Score scale not comparable | Task 3 | ✅ Covered (display-level; normalization is a separate deeper change) |
| UX-02: Score column has no scale context | Task 3 | ✅ Covered |
| S-02: Actionability threshold hidden | Task 4 | ✅ Covered |
| UX-13: Page summary is boilerplate | Task 5 | ✅ Covered |
| UX-03: "Bucket" column header jargon | Task 6 | ✅ Covered |
| UX-10: "Muted" vs "Suppressed" | Task 6 | ✅ Covered |
| UX-12: State tag internal codes | Task 6 | ✅ Covered |
| UX-14: KPI descriptions too passive | Task 6 | ✅ Covered |
| F-01: Fundamentals period mismatch bug | ❌ **Not in this plan** — tracked in `docs/audits/fundamentals-agent-audit-2026-05-30.md`; implement separately |
| OF-01, OA-01, PP-01, SM-01: Missing inspectors | ❌ **Not in this plan** — covered by Plan B (inspector completeness) |
| IN-01: No insider type weighting | ❌ **Not in this plan** — requires signal worker changes; Plan B |
| N-01: News vocabulary too simple | ❌ **Not in this plan** — requires signal worker changes; Plan B |

### Placeholder scan

No TBD, TODO, or "implement later" in any step. All code blocks are complete. All test assertions are specific.

### Type consistency check

- `_actionability_reason_text` returns `str` → used in `_signal_inspection_fields` which returns `dict[str, str]` ✅
- `_score_scale_label` and `_score_scale_tooltip` return `str` → added to row dicts as string values ✅
- `_signals_dynamic_detail` returns `str` → assigned to `detail` which is `str` ✅
- `_lane_state_display_label` returns `str` → replaces `_label_text(state)` which also returns `str` ✅
- `LaneActionabilityRule.max_actionability: str | None` → checked in `_gate_signal` against `"CONTEXT_ONLY"` string ✅

---

## Out of Scope (Plan B — Signal Inspector Completeness)

The following audit findings are deferred to a separate plan because they require building new Python evidence reconstructors — more complex and independent from this plan's display-layer changes:

- **OF-01, OA-01** — Dedicated options_flow and options_anomaly inspector panels
- **PP-01** — Dedicated prepost inspector  
- **SM-01** — Dedicated sector_momentum inspector
- **AV-01** — Volume band in abnormal volume inspector
- **IN-01** — Insider type weighting (CEO vs board member)
- **F-02** — Sector context for fundamentals margins
- **N-01** — News vocabulary improvement
- **ST-01** — Subscription thesis score weighting

---

*Plan written: 2026-05-31. Branch: `feat/ux-product-audit-20260529`.*
