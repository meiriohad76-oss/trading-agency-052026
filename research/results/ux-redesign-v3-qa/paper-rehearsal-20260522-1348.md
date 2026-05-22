# Controlled Paper-Trade Rehearsal - 2026-05-22 13:48 UTC

## Verdict

Valid no-submit safety rehearsal.

The cockpit path was exercised against the local live runtime and Alpaca paper broker validation. No paper order was submitted because the current execution preview had 0 orderable previews and the freshness gate was closed.

## Runtime Context

- Cockpit URL: `http://127.0.0.1:8000/cockpit`
- Runtime cycle: `auto-lane-refresh-20260522T131940Z`
- Market context: market-closed/off-hours validation path
- Browser QA output: `research/results/ux-redesign-v3-qa/paper-rehearsal-20260522-1348/`

## Readiness Checks

### Operational Readiness

Command:

```powershell
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
```

Result: blocked, as expected for the no-submit rehearsal.

Blockers:

- Data loaded and analyzed: 5 data blocker(s), 5 warning(s).
- Runtime cycle: `checked_at` was 1874 seconds old; refresh source-health before review.
- Human review progress: 20 candidate(s) pending.

### Local Runtime

Command:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
```

Result: pass.

Observed output:

- `health`: `ok`
- `selection_reports`: 20
- `risk_decisions`: 20
- `/` first byte: 2.06s, within 3.0s budget
- `/reports/selection` total: 2.166s, within 5.0s budget
- `source_health`: 8.0

## Execution Preview

Endpoint:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/status/execution-preview -TimeoutSec 30
```

Observed counts:

| Metric | Count |
| --- | ---: |
| Preview rows | 168 |
| Ready rows | 0 |
| Orderable paper previews | 0 |
| Submit-ready previews | 0 |
| Review-only rows | 20 |
| Blocked rows | 148 |
| Candidate blocker rows | 20 |
| Order approvals available | 0 |

Submit gate:

- Label: `Closed`
- Open: `false`
- Headline: `0 orderable paper previews are ready.`
- Freshness blocker: `massive-stock-trades source-health row is 1597s old; refresh critical evidence before submitting.`

Candidate-level blockers recorded for review/staged rows:

| Ticker | Risk | Reason |
| --- | --- | --- |
| ABNB | WARN | confirmed signal count 1 is below required 2. |
| ACN | WARN | conviction 0.56 is below paper promotion threshold 0.62. |
| ADI | WARN | confirmed signal count 1 is below required 2. |
| ADSK | WARN | conviction 0.56 is below paper promotion threshold 0.62. |
| AMZN | WARN | current human research approval is missing. |
| APP | WARN | confirmed signal count 1 is below required 2. |
| ARM | WARN | confirmed signal count 1 is below required 2. |
| CPRT | WARN | confirmed signal count 1 is below required 2. |
| CTAS | WARN | confirmed signal count 1 is below required 2. |
| EMR | WARN | conviction 0.52 is below paper promotion threshold 0.62. |
| GILD | WARN | confirmed signal count 1 is below required 2. |
| MCD | WARN | conviction 0.57 is below paper promotion threshold 0.62. |
| MCHP | WARN | confirmed signal count 1 is below required 2. |
| NVDA | WARN | confirmed signal count 1 is below required 2. |
| PAYX | WARN | conviction 0.52 is below paper promotion threshold 0.62. |
| PLTR | WARN | confirmed signal count 1 is below required 2. |
| SCHW | WARN | conviction 0.54 is below paper promotion threshold 0.62. |
| SNDK | WARN | confirmed signal count 1 is below required 2. |
| WDC | WARN | conviction 0.58 is below paper promotion threshold 0.62. |
| XEL | WARN | confirmed signal count 1 is below required 2. |

## Broker Validation

Command:

```powershell
.\.venv\Scripts\python scripts\run_paper_broker_validation.py
```

Result: pass.

Observed broker state:

- Verdict: `paper_broker_validation_passed`
- Provider: Alpaca
- Mode: paper
- Account status: ACTIVE
- Broker connected: true
- Open orders: 0
- Positions: 2
- Gross exposure: about 2.07%
- Buying power: about 198,072.56 USD

## Browser QA

Command:

```powershell
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --output research/results/ux-redesign-v3-qa/paper-rehearsal-20260522-1348
```

Result: pass.

Observed:

- `failure_count`: 0
- Viewports checked: desktop 1920, desktop 1366, kiosk 1280, mobile 390
- Console errors: none recorded
- Page errors: none recorded
- Horizontal overflow: false
- BLUF visible: true
- Phase rail visible: true
- Candidate area visible: true
- Submit gate safe: true
- Unreadable controls: none recorded

## Safety Outcome

No paper order was submitted.

This is the correct outcome for this rehearsal because:

- Broker validation was green, but
- execution preview had 0 orderable paper previews, and
- the paper submit freshness gate was closed by source-health age.

The cockpit therefore proved that the paper-submit path does not proceed when the current cycle lacks submit-ready order intent.

## New Backlog Items

1. Refresh or repair the `massive-stock-trades` source-health proof before the next live submit rehearsal.
2. Complete or clear the 20 pending human review decisions so the execution preview can stage eligible rows.
3. Re-run the paper-trade rehearsal only after execution preview reports at least 1 orderable preview.
4. Keep the no-submit branch as a regression scenario: broker green plus no orderable preview must keep paper submit closed.
