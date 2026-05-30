# Fundamentals Analysis Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the fundamentals lane from a 3-factor single-snapshot model to a PIT-safe fundamentals system that uses aligned SEC periods, historical growth trends, trailing valuation, optional forward estimates, visible data health, and a clear 12+ card evidence panel.

**Architecture:** Implement this in layers: first fix SEC period correctness, then expose PIT-safe history, then expand EDGAR tags, then upgrade scoring/detail output, then add optional yfinance/FMP forward state, then wire that state into fundamentals evidence and health. Forward providers are additive and must never make SEC-backed fundamentals unusable when absent.

**Tech Stack:** Python 3.14, pandas, polars, pytest, httpx, yfinance. Run tests with `.\.venv\Scripts\python -m pytest` from `C:\Users\meiri\trading_agency`.

**Audit reference:** `docs/audits/fundamentals-agent-audit-2026-05-30.md`

---

## Correction Summary

This plan replaces the earlier draft and fixes the execution hazards found in review:

- Period alignment must anchor every metric used in a ratio, not only `revenue` and `net_income`.
- The period-mismatch tests must include valid fixture rows and must not assert impossible annual values.
- Amended filings need explicit priority (`10-Q/A` over `10-Q`, `10-K/A` over `10-K`) when timestamps tie.
- Growth loading must not swallow arbitrary programming errors silently.
- The scoring layer must emit a stable fundamentals detail contract consumed by the dashboard.
- yfinance and FMP JSON state must be integrated into scoring/evidence and lane health, not merely written to disk.
- FMP tests must match dataclass constructor names.
- The 12-card evidence panel must depend only on fields guaranteed by the scoring/detail contract.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `research/src/pit/sec_views.py` | Period-aligned SEC fundamentals snapshot, unit validation, amendment priority, history frame |
| Modify | `research/src/pit/loader.py` | `PITLoader.fundamentals_history()` |
| Modify | `research/src/sec/company_facts_parser.py` | More XBRL tags and derived fields |
| Modify | `research/src/signals/fundamentals.py` | Quality/growth/valuation/forward sub-scores and stable detail contract |
| Create | `research/src/fundamentals/__init__.py` | Fundamentals provider package |
| Create | `research/src/fundamentals/yfinance_snapshot.py` | yfinance snapshot fetcher |
| Create | `research/src/fundamentals/fmp_client.py` | FMP earnings surprise and analyst estimate client |
| Create | `research/src/fundamentals/forward_state.py` | Read yfinance/FMP state files with freshness metadata |
| Create | `research/scripts/pull_yfinance_fundamentals.py` | yfinance state pull script |
| Create | `research/scripts/pull_fmp_earnings.py` | FMP state pull script |
| Modify | `research/src/data_refresh/jobs.py` | Register optional forward fundamentals jobs if scheduler integration is present |
| Modify | `src/agency/runtime/signal_evidence.py` | 12+ card fundamentals evidence panel |
| Modify | `src/agency/runtime/lane_state.py` | Expose forward fundamentals freshness without blocking SEC fundamentals |
| Modify | `src/agency/runtime/data_load_status.py` | Include forward fundamentals state in dashboard health payloads |
| Test | `tests/unit/test_sec_views_period_fix.py` | Period alignment tests |
| Test | `tests/unit/test_pit_loader.py` | PIT history loader tests |
| Test | `tests/unit/test_sec_parsers.py` | XBRL parser tests |
| Test | `tests/unit/test_fundamentals_growth.py` | Growth and scoring tests |
| Test | `tests/unit/test_yfinance_snapshot.py` | yfinance fetcher tests |
| Test | `tests/unit/test_fmp_client.py` | FMP client tests |
| Test | `tests/unit/test_forward_fundamentals_state.py` | Forward state freshness tests |
| Test | `tests/unit/test_signal_evidence_fundamentals.py` | Dashboard evidence tests |

---

## Shared Fundamentals Detail Contract

Every downstream UI/evidence component must rely on this contract, emitted from `research/src/signals/fundamentals.py` in the signal detail payload when data is available:

```python
{
    "filing_period": "Q3",
    "filing_year": 2026,
    "filing_form": "10-Q",
    "filing_period_end": "2026-09-30",
    "period_alignment_status": "aligned",
    "quality_score": 0.42,
    "growth_score": 0.31,
    "valuation_score": -0.10,
    "forward_score": 0.18,
    "composite_score": 0.29,
    "gross_margin": 0.44,
    "operating_margin": 0.30,
    "net_margin": 0.24,
    "fcf_margin": 0.27,
    "roe": 1.47,
    "roa": 0.31,
    "leverage": 0.85,
    "revenue_growth_qoq": 0.03,
    "revenue_growth_yoy": 0.09,
    "net_income_growth_qoq": 0.04,
    "net_income_growth_yoy": 0.12,
    "fcf_growth_qoq": 0.02,
    "fcf_growth_yoy": 0.10,
    "trailing_pe": 28.1,
    "forward_pe": 24.3,
    "forward_eps": 7.28,
    "eps_beat_rate": 0.75,
    "analyst_count": 47,
    "forward_data_status": "ready",
    "forward_data_as_of": "2026-05-30T08:00:00+00:00",
}
```

Missing optional values must be `None`, not absent. SEC-backed values are required for `composite_score`; forward provider fields are optional and must not block SEC fundamentals.

---

## TICKET-FA01: Fix SEC Period Alignment and Unit Validation

**Goal:** `fundamentals_from_frame()` must not mix annual, quarterly, amended, or wrong-unit rows when computing ratios.

**Definition of Done:**
- Monetary metrics only use `unit == "USD"`.
- Share-count metrics keep share units and are not coerced into USD.
- Anchor period is selected from a period/form family that contains the ratio-critical metrics available in that period.
- For the existing 3-factor model, ratio-critical metrics are `revenue`, `net_income`, and `free_cash_flow`.
- After FA03, ratio-critical metrics also include any present numerator used with revenue: `gross_profit`, `operating_income`, and `ebitda`.
- `10-Q/A` outranks `10-Q`, and `10-K/A` outranks `10-K` for the same metric/period.
- If no consistent anchor period exists, raise `DataNotAvailableAt`.

- [x] **Step 1: Add failing tests**

Create `tests/unit/test_sec_views_period_fix.py` with tests for:

```python
def test_uses_single_quarter_when_revenue_net_income_and_fcf_match() -> None: ...
def test_does_not_mix_quarterly_net_income_with_annual_revenue() -> None: ...
def test_does_not_mix_free_cash_flow_from_different_period() -> None: ...
def test_falls_back_to_latest_consistent_annual_period() -> None: ...
def test_raises_when_no_consistent_period_has_required_metrics() -> None: ...
def test_amended_filing_wins_for_same_metric_period_and_form_family() -> None: ...
def test_wrong_unit_usd_row_is_ignored_for_monetary_metric() -> None: ...
```

Critical fixture correction for the old bad test:

```python
frame = _make_frame([
    _row("revenue", 400_000.0, "10-K", "FY", date(2023, 12, 31)),
    _row("net_income", 90_000.0, "10-K", "FY", date(2023, 12, 31)),
    _row("free_cash_flow", 80_000.0, "10-K", "FY", date(2023, 12, 31)),
    _row("net_income", 25_000.0, "10-Q", "Q3", date(2024, 9, 30)),
])
result = fundamentals_from_frame(frame, as_of=AS_OF)
assert result.value["revenue"] == 400_000.0
assert result.value["net_income"] == 90_000.0
assert result.value["free_cash_flow"] == 80_000.0
```

- [x] **Step 2: Run the failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_sec_views_period_fix.py -v
```

Expected: failures proving current `fundamentals_from_frame()` selects latest metric independently.

- [x] **Step 3: Implement in `research/src/pit/sec_views.py`**

Implementation requirements:

```python
_MONETARY_METRICS = frozenset({
    "revenue", "net_income", "operating_cash_flow", "capital_expenditures",
    "free_cash_flow", "total_assets", "total_liabilities", "gross_profit",
    "operating_income", "ebitda", "depreciation_amortization",
    "research_development", "interest_expense", "income_tax_expense",
    "current_assets", "current_liabilities", "long_term_debt",
    "cash_and_equivalents", "total_equity", "retained_earnings",
})

_BASE_REQUIRED_ANCHOR_METRICS = frozenset({"revenue", "net_income", "free_cash_flow"})
_OPTIONAL_REVENUE_NUMERATORS = frozenset({"gross_profit", "operating_income", "ebitda"})
_QUARTERLY_PERIODS = frozenset({"Q1", "Q2", "Q3", "Q4"})
```

Use a deterministic helper:

```python
def _form_family(form: object) -> str:
    return str(form or "").upper().replace("/A", "")

def _amendment_rank(form: object) -> int:
    return 1 if str(form or "").upper().endswith("/A") else 0
```

Anchor selection must:

1. Drop wrong-unit monetary rows.
2. Add `_form_family` and `_amendment_rank`.
3. Deduplicate by `metric`, `__period_end`, `fiscal_period`, `_form_family`, preferring highest `_amendment_rank`, then latest `__as_of`.
4. Prefer quarterly groups over annual groups.
5. For each group, require the intersection of available ratio-critical metrics, starting with the base required set. Do not anchor on a group missing `free_cash_flow` while using `free_cash_flow` from another group.
6. Return all metrics from that anchor group, then add non-ratio context fields from same form family only if clearly labeled as context fields.

- [x] **Step 4: Run regression**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_sec_views_period_fix.py tests\unit\test_fundamentals_signal.py -v
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add research/src/pit/sec_views.py tests/unit/test_sec_views_period_fix.py
git commit -m "fix(fundamentals): align SEC metrics to consistent fiscal periods"
```

---

## TICKET-FA02: Add PIT Fundamentals History

**Goal:** Provide PIT-safe historical SEC periods for trend computation.

**Definition of Done:**
- `PITLoader.fundamentals_history(ticker, as_of, n_periods=8)` exists.
- It returns a pandas DataFrame with `metric`, `value`, `period_end`, `fiscal_period`, `form`, `filing_date`, and `source_id`.
- It uses the same unit validation and amendment priority as FA01.
- It only returns rows known on or before `as_of`.

- [x] **Step 1: Add tests to `tests/unit/test_pit_loader.py`**

Add two tests:

```python
def test_fundamentals_history_returns_last_periods_oldest_first(tmp_path: Path) -> None: ...
def test_fundamentals_history_respects_as_of_cutoff(tmp_path: Path) -> None: ...
```

- [x] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_pit_loader.py -v
```

Expected: `AttributeError` for missing `fundamentals_history`.

- [x] **Step 3: Implement**

In `research/src/pit/sec_views.py`, add `fundamentals_history_frame(frame, as_of, n_periods=8)`.

In `research/src/pit/loader.py`, add:

```python
def fundamentals_history(self, ticker: str, as_of: date, n_periods: int = 8) -> pd.DataFrame:
    frame = self._ticker_frame(DatasetName.SEC_COMPANY_FACTS, ticker, as_of)
    frame = self._with_date(frame, "period_end", "__period_end", DatasetName.SEC_COMPANY_FACTS, as_of)
    return fundamentals_history_frame(frame, as_of=as_of, n_periods=n_periods).to_pandas()
```

Import pandas and `fundamentals_history_frame` as needed.

- [x] **Step 4: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_pit_loader.py tests\unit\test_sec_views_period_fix.py -v
```

- [x] **Step 5: Commit**

```powershell
git add research/src/pit/sec_views.py research/src/pit/loader.py tests/unit/test_pit_loader.py
git commit -m "feat(fundamentals): expose PIT fundamentals history"
```

---

## TICKET-FA03: Expand EDGAR XBRL Tags

**Goal:** Extract enough SEC metrics to support quality, growth, and trailing valuation.

**Definition of Done:**
- `METRIC_TAGS` includes tags for: `gross_profit`, `operating_income`, `ebitda`, `depreciation_amortization`, `research_development`, `interest_expense`, `income_tax_expense`, `eps_basic`, `eps_diluted`, `current_assets`, `current_liabilities`, `long_term_debt`, `cash_and_equivalents`, `total_equity`, `retained_earnings`.
- Free cash flow derivation remains unchanged and tested.
- Parser tests verify at least one common XBRL tag per new metric.

- [x] **Step 1: Add parser tests**

Append tests to `tests/unit/test_sec_parsers.py`:

```python
def test_parser_extracts_profitability_statement_tags() -> None: ...
def test_parser_extracts_balance_sheet_tags() -> None: ...
def test_parser_extracts_eps_tags_with_pure_unit() -> None: ...
def test_free_cash_flow_derivation_still_works_with_expanded_tags() -> None: ...
```

- [x] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_sec_parsers.py -v
```

- [x] **Step 3: Implement tag map**

Add conservative SEC tag mappings only. Do not add speculative aliases that are not present in SEC company facts.

- [x] **Step 4: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_sec_parsers.py tests\unit\test_sec_views_period_fix.py -v
```

- [x] **Step 5: Commit**

```powershell
git add research/src/sec/company_facts_parser.py tests/unit/test_sec_parsers.py
git commit -m "feat(fundamentals): expand SEC company facts metrics"
```

---

## TICKET-FA04: Upgrade Fundamentals Scoring and Detail Contract

**Goal:** `fundamental_factor_frame()` emits the shared detail contract and computes sub-scores from SEC-backed quality, growth, and trailing valuation factors.

**Definition of Done:**
- Existing `fundamental_score(as_of, universe, loader)` still works without optional loaders.
- Optional `history_loader` adds growth fields.
- Optional `price_loader` adds trailing valuation fields.
- Unexpected exceptions from loaders are logged or raised in tests; only `DataNotAvailableAt` is treated as unavailable data.
- Output includes all shared contract keys, with `None` for missing optional fields.
- Composite score uses four transparent sub-scores:
  - `quality_score`: margins, ROE/ROA when available, inverse leverage.
  - `growth_score`: revenue/net income/FCF QoQ and YoY.
  - `valuation_score`: inverse trailing P/E and FCF yield when price/share data available.
  - `forward_score`: remains `None` until FA07.

- [x] **Step 1: Add tests**

Create `tests/unit/test_fundamentals_growth.py` with tests:

```python
def test_returns_shared_detail_contract_keys_without_optional_loaders() -> None: ...
def test_revenue_growth_yoy_matches_same_quarter_last_year() -> None: ...
def test_growth_uses_period_end_not_row_order() -> None: ...
def test_single_period_history_returns_none_growth_without_crashing() -> None: ...
def test_loader_programming_error_is_not_silently_swallowed() -> None: ...
def test_composite_score_uses_quality_and_growth_when_available() -> None: ...
```

Key assertion for the no-swallow rule:

```python
class BrokenHistoryLoader:
    def fundamentals_history(self, ticker: str, as_of: date, n_periods: int = 8) -> pd.DataFrame:
        raise KeyError("schema drift")

with pytest.raises(KeyError):
    fundamental_factor_frame(AS_OF, {"AAPL"}, loader, history_loader=BrokenHistoryLoader())
```

- [x] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fundamentals_growth.py -v
```

- [x] **Step 3: Implement scoring**

Modify `research/src/signals/fundamentals.py`:

```python
class FundamentalsHistoryLoader(Protocol):
    def fundamentals_history(self, ticker: str, as_of: date, n_periods: int = 8) -> pd.DataFrame: ...

class FundamentalsPriceLoader(Protocol):
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pd.DataFrame: ...
```

Rules:
- Catch `DataNotAvailableAt` only for optional history/price. Do not catch `Exception`.
- Use z-scores only when at least `MIN_CROSS_SECTION` non-null values exist.
- Use `None` for unavailable growth/valuation fields.
- Keep old score behavior green for existing tests.

- [x] **Step 4: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fundamentals_growth.py tests\unit\test_fundamentals_signal.py -v
```

- [x] **Step 5: Commit**

```powershell
git add research/src/signals/fundamentals.py tests/unit/test_fundamentals_growth.py
git commit -m "feat(fundamentals): add SEC growth and quality detail contract"
```

---

## TICKET-FA05: Add yfinance Forward Snapshot Pull

**Goal:** Pull optional forward valuation and analyst fields into state files.

**Definition of Done:**
- `research/src/fundamentals/yfinance_snapshot.py` has `YfinanceSnapshot` and `pull_yfinance_snapshot(ticker)`.
- Script writes `research/data/state/fundamentals/yfinance/{TICKER}.json`.
- Missing yfinance fields become `None`.
- Network/provider failures return a clear per-ticker error in the script and do not corrupt existing state.

- [ ] **Step 1: Add tests**

Create `tests/unit/test_yfinance_snapshot.py` with tests for:

```python
def test_pull_returns_forward_pe_and_targets() -> None: ...
def test_pull_handles_missing_fields_as_none() -> None: ...
def test_pull_raises_fetch_error_on_provider_exception() -> None: ...
def test_snapshot_to_dict_is_json_serializable() -> None: ...
```

- [ ] **Step 2: Implement package and fetcher**

Create `research/src/fundamentals/__init__.py` and `research/src/fundamentals/yfinance_snapshot.py`.

Fields:

```python
forward_pe, trailing_pe, forward_eps, trailing_eps, peg_ratio,
analyst_mean_target, analyst_median_target, analyst_count,
revenue_growth, earnings_growth, return_on_equity, return_on_assets,
operating_margins, profit_margins, fetched_at
```

- [ ] **Step 3: Add script**

Create `research/scripts/pull_yfinance_fundamentals.py` with `--tickers`, `--universe-file`, `--delay`, and `--output-dir`.

- [ ] **Step 4: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_yfinance_snapshot.py -v
.\.venv\Scripts\python research\scripts\pull_yfinance_fundamentals.py --tickers AAPL MSFT --delay 0.1
```

- [ ] **Step 5: Commit**

```powershell
git add research/src/fundamentals research/scripts/pull_yfinance_fundamentals.py tests/unit/test_yfinance_snapshot.py
git commit -m "feat(fundamentals): add yfinance forward snapshot state"
```

---

## TICKET-FA06: Add FMP Earnings Surprise and Estimates Pull

**Goal:** Add optional FMP forward/earnings evidence with a tested client and state script.

**Definition of Done:**
- `FmpEarningsSurprise` constructor and tests use fields `actual_eps` and `estimated_eps`.
- `FmpClient.earnings_surprises()` and `FmpClient.analyst_estimates()` return structured dataclasses.
- Missing `FMP_API_KEY` yields empty state with status `not_configured`, not a crash.
- HTTP errors are captured as per-ticker provider errors in the script.

- [ ] **Step 1: Add tests**

Create `tests/unit/test_fmp_client.py`:

```python
def test_earnings_surprises_returns_structured_objects() -> None: ...
def test_analyst_estimates_returns_structured_objects() -> None: ...
def test_returns_empty_list_on_404() -> None: ...
def test_beat_rate_computed_correctly() -> None:
    surprises = [
        FmpEarningsSurprise(date="2024-11-01", ticker="AAPL", actual_eps=1.64, estimated_eps=1.60),
        FmpEarningsSurprise(date="2024-08-01", ticker="AAPL", actual_eps=1.40, estimated_eps=1.45),
        FmpEarningsSurprise(date="2024-05-01", ticker="AAPL", actual_eps=1.53, estimated_eps=1.50),
        FmpEarningsSurprise(date="2024-02-01", ticker="AAPL", actual_eps=2.18, estimated_eps=2.10),
    ]
    assert compute_beat_rate(surprises) == pytest.approx(0.75)
```

- [ ] **Step 2: Implement client and script**

Create `research/src/fundamentals/fmp_client.py` and `research/scripts/pull_fmp_earnings.py`.

Document `FMP_API_KEY=` in `.env.example`.

- [ ] **Step 3: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fmp_client.py -v
```

If an API key is configured:

```powershell
.\.venv\Scripts\python research\scripts\pull_fmp_earnings.py --tickers AAPL --delay 0.1
```

- [ ] **Step 4: Commit**

```powershell
git add research/src/fundamentals/fmp_client.py research/scripts/pull_fmp_earnings.py tests/unit/test_fmp_client.py .env.example
git commit -m "feat(fundamentals): add FMP earnings and analyst estimate state"
```

---

## TICKET-FA07: Integrate Forward State Into Fundamentals and Health

**Goal:** Make yfinance/FMP state visible and usable without letting optional forward providers block SEC fundamentals.

**Definition of Done:**
- `research/src/fundamentals/forward_state.py` reads yfinance and FMP JSON state for a ticker.
- It returns `forward_data_status`: `ready`, `missing`, `expired`, `not_configured`, or `provider_error`.
- It exposes `forward_data_as_of`, provider names, and a plain-English `forward_data_detail`.
- `fundamental_factor_frame()` accepts `forward_loader` and fills `forward_pe`, `forward_eps`, `eps_beat_rate`, `analyst_count`, and `forward_score`.
- Dashboard/source health can show optional forward data as a warning, never a blocker for SEC-backed fundamentals.

- [ ] **Step 1: Add tests**

Create `tests/unit/test_forward_fundamentals_state.py`:

```python
def test_reads_yfinance_and_fmp_state_for_ticker() -> None: ...
def test_missing_state_returns_missing_status() -> None: ...
def test_old_state_returns_expired_status() -> None: ...
def test_forward_score_is_none_when_optional_state_missing() -> None: ...
def test_forward_state_health_is_warning_not_blocker() -> None: ...
```

- [ ] **Step 2: Implement state reader**

Create `research/src/fundamentals/forward_state.py` with:

```python
class ForwardFundamentalsLoader(Protocol):
    def forward_fundamentals(self, ticker: str, as_of: date) -> dict[str, object]: ...
```

Default freshness SLA: 7 calendar days for yfinance/FMP forward state unless config says otherwise.

- [ ] **Step 3: Wire into scoring**

Modify `research/src/signals/fundamentals.py` so optional forward fields populate the shared detail contract. If state is not `ready`, set forward fields to `None` and keep SEC-based score valid.

- [ ] **Step 4: Wire health**

Use `src/agency/runtime/lane_state.py` and `src/agency/runtime/data_load_status.py`. The displayed wording must be:

- `Forward fundamentals ready`
- `Forward fundamentals not configured`
- `Forward fundamentals needs refresh`
- `Forward fundamentals provider error`

- [ ] **Step 5: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_forward_fundamentals_state.py tests\unit\test_fundamentals_growth.py -v
```

- [ ] **Step 6: Commit**

```powershell
git add research/src/fundamentals/forward_state.py research/src/signals/fundamentals.py src/agency/runtime/lane_state.py src/agency/runtime/data_load_status.py tests/unit/test_forward_fundamentals_state.py
git commit -m "feat(fundamentals): integrate optional forward state and health"
```

---

## TICKET-FA08: Upgrade Fundamentals Evidence Panel

**Goal:** Show a clear, bottom-line-first fundamentals panel backed by the shared detail contract.

**Definition of Done:**
- `_fundamentals_evidence()` returns 12+ cards.
- Missing optional fields show `n/a`.
- Headline includes ticker, filing period, form, and composite score.
- Detail explains SEC period alignment and whether forward data was ready.
- Positive margins/growth are green; negative growth is red; high leverage is red.
- No card depends on a field not emitted by the shared detail contract.

- [ ] **Step 1: Add tests**

Create `tests/unit/test_signal_evidence_fundamentals.py`:

```python
def test_fundamentals_evidence_has_12_cards() -> None: ...
def test_headline_includes_filing_period_and_form() -> None: ...
def test_positive_net_margin_gets_pass_tone() -> None: ...
def test_negative_revenue_growth_gets_block_tone() -> None: ...
def test_missing_forward_data_shows_plain_language_status() -> None: ...
```

- [ ] **Step 2: Implement evidence panel**

Modify `src/agency/runtime/signal_evidence.py`.

Cards:

1. Gross margin
2. Operating margin
3. Net margin
4. FCF margin
5. ROE
6. ROA
7. Leverage
8. Revenue growth YoY
9. Net income growth YoY
10. FCF growth YoY
11. Trailing P/E
12. Forward P/E
13. EPS beat rate
14. Analyst count
15. Composite score
16. Filing period

- [ ] **Step 3: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_signal_evidence_fundamentals.py tests\unit\test_fundamentals_signal.py -v
```

- [ ] **Step 4: Visual QA**

Start the server, open a candidate with a fundamentals signal, and confirm:

- The panel is readable.
- The period label is visible.
- Optional forward data status is visible.
- No generic card text appears.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/runtime/signal_evidence.py tests/unit/test_signal_evidence_fundamentals.py
git commit -m "feat(fundamentals): add detailed fundamentals evidence panel"
```

---

## TICKET-FA09: Full Regression and Live Data Smoke

**Goal:** Prove the upgraded fundamentals path is safe for the live 168-stock agency universe.

**Definition of Done:**
- Targeted fundamentals tests pass.
- Full unit suite passes or every unrelated failure is documented with evidence.
- A live SEC-backed fundamentals smoke confirms the agency universe remains 168 and no bootstrap/test data is used.
- Candidate detail displays real SEC-backed fundamentals evidence.

- [ ] **Step 1: Run targeted suite**

```powershell
.\.venv\Scripts\python -m pytest `
  tests\unit\test_sec_views_period_fix.py `
  tests\unit\test_pit_loader.py `
  tests\unit\test_sec_parsers.py `
  tests\unit\test_fundamentals_signal.py `
  tests\unit\test_fundamentals_growth.py `
  tests\unit\test_yfinance_snapshot.py `
  tests\unit\test_fmp_client.py `
  tests\unit\test_forward_fundamentals_state.py `
  tests\unit\test_signal_evidence_fundamentals.py -v
```

- [ ] **Step 2: Run full unit suite**

```powershell
.\.venv\Scripts\python -m pytest tests\unit -q
```

- [ ] **Step 3: Run no-test-data smoke**

```powershell
npm run check:no-bootstrap-data
```

Expected: tracked allowed universe remains 168 and forbidden runtime markers remain 0.

- [ ] **Step 4: Run local runtime smoke**

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
```

- [ ] **Step 5: Manual dashboard QA**

Open the app and verify one candidate detail page:

- SEC filing period is readable.
- Fundamentals cards are evidence-backed.
- Forward provider status is visible.
- Optional forward-data warning does not block paper-trade review.

- [ ] **Step 6: Commit verification docs if created**

```powershell
git status --short
```

If a QA note is created, save it under `docs/audits/` and commit it with the code.

---

## Acceptance Criteria

| AC | Verification |
|---|---|
| SEC period mismatch fixed | `test_sec_views_period_fix.py` passes |
| Ratio metrics aligned | Tests cover `revenue`, `net_income`, and `free_cash_flow` |
| Amended filings prioritized | Amendment test passes |
| PIT history available | `test_pit_loader.py` history tests pass |
| Expanded EDGAR tags parse | `test_sec_parsers.py` expanded tag tests pass |
| Growth trends computed | `test_fundamentals_growth.py` passes |
| Unexpected loader bugs not swallowed | `test_loader_programming_error_is_not_silently_swallowed` passes |
| yfinance state works | `test_yfinance_snapshot.py` passes |
| FMP state works | `test_fmp_client.py` passes |
| Forward state integrated | `test_forward_fundamentals_state.py` passes |
| Evidence panel is user-readable | `test_signal_evidence_fundamentals.py` and visual QA pass |
| No test/bootstrap fundamentals data | `npm run check:no-bootstrap-data` passes |
| Full unit regression | `.\.venv\Scripts\python -m pytest tests\unit -q` passes or unrelated failures are documented |
