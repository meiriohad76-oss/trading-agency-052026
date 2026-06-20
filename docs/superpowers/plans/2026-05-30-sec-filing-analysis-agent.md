# SEC Filing Analysis Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an agent that detects new SEC filings for universe tickers, extracts key text (earnings results, MD&A, material events, forward guidance), analyzes them with an LLM, and surfaces the analysis as a new `sec_filing_analysis` signal lane in the existing candidate review workflow.

**Architecture:** Three layers: (1) Filing Monitor — polls EDGAR for new filings and writes a state file of what's new since last check; (2) Filing Analyst — fetches the document, extracts key sections (MD&A, Item 2.02, guidance), calls the existing OpenAI provider with a structured prompt, stores a JSON analysis per filing; (3) Signal Integration — maps the filing analysis to the existing signal/evidence pipeline so operators see it on the Signals page and candidate detail page. The LLM analysis is optional — if OPENAI_API_KEY is absent, the filing is still detected and stored with raw text only.

**Tech Stack:** Python 3.14, httpx (already installed), existing `research/src/sec/client.py` (`SecClient`), existing `research/src/sec/submissions.py` (`FilingSummary`, `parse_recent_filings`), existing OpenAI LLM review infrastructure (`src/agency/services/llm_review.py`), APScheduler (already installed), Jinja2 templates.

**Audit reference:** `docs/audits/fundamentals-agent-audit-2026-05-30.md` § SEC Filing Analysis Agent design.

---

## Which Filing Types to Analyze

| Form | What it is | Why | Trigger cadence |
|---|---|---|---|
| **8-K Item 2.02** | Earnings release + guidance | Most time-sensitive. Announces revenue/EPS vs. estimates; often contains forward guidance for next quarter. Filed within 4 business days of earnings. | Within hours of filing |
| **10-Q** | Quarterly report | Full MD&A, risk factors, financial statements. Contains forward-looking language and management discussion. Filed 40–45 days after quarter end. | Within 24h of filing |
| **10-K** | Annual report | Most comprehensive view of the business: strategy, risks, competitive position, full-year results. Filed 60–75 days after fiscal year end. | Within 48h of filing |
| **8-K Item 1.01** | Material agreements | Signals M&A, major partnerships, or contract wins/losses. | Within hours of filing |
| **SC 13D** | Activist investor entering >5% stake | Strong bullish catalyst; activist typically has a value-creation thesis. | Within hours of filing |

The agent processes all five. Items 8-K 2.02, 10-Q, and 10-K produce full LLM analysis. Items 8-K 1.01 and SC 13D produce a shorter summary analysis.

---

## Codebase Context

Before writing any code, read:
- `research/src/sec/client.py` — `SecClient`, `SecClientConfig`, `archive_url()`; async httpx client with rate limiting (4 req/s).
- `research/src/sec/submissions.py` — `FilingSummary` dataclass, `parse_recent_filings()`.
- `research/src/sec/company_facts.py` — Pattern for how a pull script uses `SecClient`.
- `src/agency/services/llm_review.py` — `OpenAILlmReviewProvider`, `LlmReviewResult`; see how the existing LLM review is structured.
- `research/src/live_runtime/config.py` — `LANE_CONFIGS` dict, `RuntimeLaneConfig`; add the new lane here.
- `src/agency/runtime/lane_promotion.py` — `LANE_PROMOTION_POLICIES`; add new lane policy.
- `src/agency/runtime/signal_evidence.py` — `_fundamentals_evidence()` pattern; new `_sec_filing_evidence()` follows the same structure.

The EDGAR submissions endpoint:
`https://data.sec.gov/submissions/CIK{cik_padded}.json`
Returns filing history including `filings.recent` with arrays: `accessionNumber`, `filingDate`, `form`, `primaryDocument`.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `research/src/sec/filing_fetcher.py` | Fetch filing document HTML/text from EDGAR archives |
| Create | `research/src/sec/filing_extractor.py` | Extract key sections from filing text (MD&A, Item 2.02, guidance) |
| Create | `research/src/sec/filing_monitor.py` | Check EDGAR for filings newer than a stored checkpoint date |
| Create | `research/src/fundamentals/filing_analyst.py` | LLM analysis of extracted filing sections |
| Create | `research/src/signals/sec_filing.py` | Signal score from filing analysis |
| Create | `research/scripts/run_sec_filing_monitor.py` | Pull + analyze script for the scheduler |
| Modify | `research/src/live_runtime/config.py` | Add `sec_filing_analysis` to `LANE_CONFIGS` |
| Modify | `research/src/pit/manifest.py` | Add `DatasetName.SEC_FILINGS` for the filing checkpoint store |
| Modify | `src/agency/runtime/lane_promotion.py` | Add `sec_filing_analysis` promotion policy |
| Modify | `src/agency/runtime/signal_evidence.py` | Add `_sec_filing_evidence()` |
| Create | `tests/unit/test_sec_filing_monitor.py` | Tests for the monitor |
| Create | `tests/unit/test_sec_filing_extractor.py` | Tests for section extraction |
| Create | `tests/unit/test_filing_analyst.py` | Tests for the LLM analyst (mocked) |
| Create | `tests/unit/test_sec_filing_signal.py` | Tests for the signal layer |

---

## TICKET-SFA01: Filing Monitor — Detect New EDGAR Filings

**Description:** Build a monitor that checks EDGAR for new filings since a stored checkpoint date for each ticker in the active universe. Stores the checkpoint in `research/data/state/sec_filings/checkpoint.json`. Returns a list of `FilingSummary` objects for filings that are new since the last check.

**Definition of Done:**
- `FilingMonitor.check_new_filings(tickers, since)` returns `list[FilingSummary]` filtered to forms `["8-K", "10-Q", "10-K", "SC 13D"]`.
- Checkpoint is read/written atomically.
- 4 unit tests pass.
- `FilingMonitor` uses existing `SecClient` — no new HTTP library.

**Testing & QA:**
- Unit: `tests/unit/test_sec_filing_monitor.py` (4 tests, using `unittest.mock.AsyncMock`)
- Run: `python -m pytest tests/unit/test_sec_filing_monitor.py -v`

---

- [ ] **Step 1: Write failing tests in `tests/unit/test_sec_filing_monitor.py`**

```python
# tests/unit/test_sec_filing_monitor.py
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sec.filing_monitor import FilingCheckpoint, FilingMonitor

FORMS_OF_INTEREST = {"8-K", "10-Q", "10-K", "SC 13D"}


def _submissions_payload(filings: list[dict]) -> dict:
    """Build a fake EDGAR submissions API response."""
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [f["accession"] for f in filings],
                "filingDate":     [f["date"] for f in filings],
                "reportDate":     [f.get("report_date", f["date"]) for f in filings],
                "form":           [f["form"] for f in filings],
                "primaryDocument": [f.get("doc", "filing.htm") for f in filings],
            }
        },
    }


def test_check_new_filings_returns_filings_since_date() -> None:
    client = MagicMock()
    client.submissions = AsyncMock(return_value=_submissions_payload([
        {"accession": "0001-new-8k",  "date": "2024-11-05", "form": "8-K"},
        {"accession": "0002-old-10q", "date": "2024-09-15", "form": "10-Q"},  # before cutoff
    ]))

    monitor = FilingMonitor(
        client=client,
        cik_map={"AAPL": "0000320193"},
    )
    results = asyncio.run(monitor.check_new_filings(["AAPL"], since=date(2024, 11, 1)))

    assert len(results) == 1
    assert results[0].accession_number == "0001-new-8k"
    assert results[0].form == "8-K"
    assert results[0].ticker == "AAPL"


def test_filters_to_forms_of_interest() -> None:
    client = MagicMock()
    client.submissions = AsyncMock(return_value=_submissions_payload([
        {"accession": "0001-10q",  "date": "2024-11-01", "form": "10-Q"},
        {"accession": "0002-s1",   "date": "2024-11-02", "form": "S-1"},   # not of interest
        {"accession": "0003-13d",  "date": "2024-11-03", "form": "SC 13D"},
    ]))

    monitor = FilingMonitor(client=client, cik_map={"AAPL": "0000320193"})
    results = asyncio.run(monitor.check_new_filings(["AAPL"], since=date(2024, 10, 1)))

    forms = {r.form for r in results}
    assert "S-1" not in forms
    assert "10-Q" in forms
    assert "SC 13D" in forms


def test_checkpoint_is_written_and_read(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    cp = FilingCheckpoint(path=checkpoint_path)

    cp.save(date(2024, 11, 15))
    loaded = cp.load()

    assert loaded == date(2024, 11, 15)


def test_returns_empty_when_no_cik_mapping() -> None:
    client = MagicMock()
    monitor = FilingMonitor(client=client, cik_map={})

    results = asyncio.run(monitor.check_new_filings(["UNKNOWN"], since=date(2024, 1, 1)))

    assert results == []
    client.submissions.assert_not_called()
```

- [ ] **Step 2: Run — confirm failure**

```
python -m pytest tests/unit/test_sec_filing_monitor.py -v
```

Expected: `ImportError: cannot import name 'FilingCheckpoint' from 'sec.filing_monitor'`

- [ ] **Step 3: Create `research/src/sec/filing_monitor.py`**

```python
# research/src/sec/filing_monitor.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sec.client import SecClient
from sec.submissions import FilingSummary, parse_recent_filings

FORMS_OF_INTEREST: frozenset[str] = frozenset({"8-K", "10-Q", "10-K", "SC 13D"})

DEFAULT_CHECKPOINT_PATH = (
    Path(__file__).resolve().parents[3] /
    "data" / "state" / "sec_filings" / "checkpoint.json"
)


@dataclass
class AnnotatedFilingSummary(FilingSummary):
    """FilingSummary with ticker attached."""
    ticker: str = ""


@dataclass
class FilingCheckpoint:
    path: Path = DEFAULT_CHECKPOINT_PATH

    def load(self) -> date | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return date.fromisoformat(str(payload.get("since", "")))
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def save(self, since: date) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"since": since.isoformat(), "saved_at": datetime.now(UTC).isoformat()}),
            encoding="utf-8",
        )


class FilingMonitor:
    """Check EDGAR for new filings for a set of tickers since a cutoff date."""

    def __init__(
        self,
        *,
        client: SecClient,
        cik_map: dict[str, str],          # ticker → CIK string (zero-padded 10 digits)
        forms: frozenset[str] = FORMS_OF_INTEREST,
    ) -> None:
        self._client = client
        self._cik_map = {ticker.upper(): cik for ticker, cik in cik_map.items()}
        self._forms = forms

    async def check_new_filings(
        self,
        tickers: list[str],
        *,
        since: date,
    ) -> list[AnnotatedFilingSummary]:
        """Return filings for ``tickers`` with filing_date > ``since``."""
        results: list[AnnotatedFilingSummary] = []
        for ticker in tickers:
            cik = self._cik_map.get(ticker.upper())
            if cik is None:
                continue
            try:
                payload = await self._client.submissions(cik)
            except Exception:
                continue
            summaries = parse_recent_filings(
                cik=cik,
                payload=payload,
                forms=self._forms,
                start_date=since.isoformat(),
            )
            for s in summaries:
                results.append(
                    AnnotatedFilingSummary(
                        cik=s.cik,
                        accession_number=s.accession_number,
                        filing_date=s.filing_date,
                        report_date=s.report_date,
                        form=s.form,
                        primary_document=s.primary_document,
                        ticker=ticker.upper(),
                    )
                )
        return results
```

Also verify that `AnnotatedFilingSummary` inherits correctly. The parent `FilingSummary` is a frozen dataclass — we need to NOT use `@dataclass(frozen=True)` on the subclass or we need to add `ticker` via `__init_subclass__`. Simplest: don't inherit, just add ticker to a wrapper:

```python
@dataclass
class AnnotatedFilingSummary:
    ticker: str
    cik: str
    accession_number: str
    filing_date: str
    report_date: str | None
    form: str
    primary_document: str

    @property
    def document_url(self) -> str:
        from sec.client import archive_url
        return archive_url(self.cik, self.accession_number, self.primary_document)
```

- [ ] **Step 4: Run tests — confirm 4 pass**

```
python -m pytest tests/unit/test_sec_filing_monitor.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```
git add research/src/sec/filing_monitor.py tests/unit/test_sec_filing_monitor.py
git commit -m "feat(sec-filing-agent): add FilingMonitor to detect new 8-K/10-Q/10-K/SC13D filings

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## TICKET-SFA02: Filing Document Fetcher & Text Extractor

**Description:** Fetch the HTML filing document from EDGAR archives and extract the key sections needed for analysis: for 8-K, extract the Item 2.02 text and any attached exhibit; for 10-Q/10-K, extract the MD&A section; for SC 13D, extract the Purpose and Plans section.

**Definition of Done:**
- `FilingFetcher.fetch_text(filing)` downloads and returns raw HTML/text ≤ 250KB (truncated if larger).
- `FilingExtractor.extract(form, text)` returns a `FilingExtract` with `sections: dict[str, str]`.
- 5 unit tests pass with fixture HTML.
- Extraction is resilient: never raises on malformed input, returns partial or empty sections.

**Testing & QA:**
- Unit: `tests/unit/test_sec_filing_extractor.py` (5 tests)
- Run: `python -m pytest tests/unit/test_sec_filing_extractor.py -v`

---

- [ ] **Step 1: Write failing tests in `tests/unit/test_sec_filing_extractor.py`**

```python
# tests/unit/test_sec_filing_extractor.py
from __future__ import annotations

import pytest
from sec.filing_extractor import FilingExtract, FilingExtractor


def test_extract_item_202_from_8k() -> None:
    html = """
    <html><body>
    <p><b>Item 2.02 Results of Operations and Financial Condition</b></p>
    <p>Apple reported quarterly revenue of $94.9 billion, an increase of 6 percent year over year.</p>
    <p>EPS was $1.64 compared to $1.46 in the year-ago quarter.</p>
    <p><b>Item 9.01 Financial Statements</b></p>
    <p>See exhibit.</p>
    </body></html>
    """
    extractor = FilingExtractor()
    result = extractor.extract("8-K", html)

    assert isinstance(result, FilingExtract)
    assert "2.02" in result.sections or "results_of_operations" in result.sections
    primary_text = result.primary_text
    assert "revenue" in primary_text.lower() or "$94.9" in primary_text


def test_extract_mda_from_10q() -> None:
    html = """
    <html><body>
    <p>PART I — FINANCIAL INFORMATION</p>
    <p><b>Item 2. Management's Discussion and Analysis</b></p>
    <p>Our revenue increased 8% year over year driven by strong iPhone performance.
    Looking ahead, we expect continued growth in services.</p>
    <p><b>Item 3. Quantitative Disclosures</b></p>
    <p>Other content here.</p>
    </body></html>
    """
    extractor = FilingExtractor()
    result = extractor.extract("10-Q", html)

    assert "mda" in result.sections or len(result.primary_text) > 50
    assert "revenue" in result.primary_text.lower()


def test_extraction_returns_empty_on_blank_html() -> None:
    extractor = FilingExtractor()
    result = extractor.extract("10-Q", "")

    assert isinstance(result, FilingExtract)
    assert result.primary_text == "" or len(result.primary_text) < 10


def test_truncation_at_max_chars() -> None:
    """Very long documents are truncated to avoid overwhelming the LLM."""
    long_text = "A" * 200_000
    extractor = FilingExtractor(max_chars=50_000)
    result = extractor.extract("10-Q", f"<html><body>{long_text}</body></html>")

    assert len(result.primary_text) <= 50_100  # small tolerance for HTML tags


def test_sc_13d_extracts_purpose_section() -> None:
    html = """
    <html><body>
    <p><b>Item 4. Purpose of Transaction</b></p>
    <p>The Reporting Person acquired shares to encourage management to consider strategic alternatives
    including a sale of the company.</p>
    <p><b>Item 5. Interest in Securities</b></p>
    <p>5.2% of outstanding shares.</p>
    </body></html>
    """
    extractor = FilingExtractor()
    result = extractor.extract("SC 13D", html)

    assert "purpose" in result.primary_text.lower() or "strategic" in result.primary_text.lower()
```

- [ ] **Step 2: Run — confirm failure**

```
python -m pytest tests/unit/test_sec_filing_extractor.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `research/src/sec/filing_extractor.py`**

```python
# research/src/sec/filing_extractor.py
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Matches Item N.NN or Item N headings in 8-K/10-Q/10-K filings
_ITEM_PATTERN = re.compile(
    r"item\s+(\d+(?:\.\d+)?)[.\s]",
    re.IGNORECASE,
)

# Items we care about per form type (lower-case item IDs)
_ITEMS_OF_INTEREST: dict[str, list[str]] = {
    "8-K":    ["2.02", "1.01", "5.02", "4.01"],
    "10-Q":   ["2"],    # MD&A = Item 2 in Part I
    "10-K":   ["7"],    # MD&A = Item 7
    "SC 13D": ["4"],    # Purpose of Transaction
}

_MAX_CHARS_DEFAULT = 120_000


@dataclass
class FilingExtract:
    form: str
    sections: dict[str, str] = field(default_factory=dict)
    raw_text: str = ""

    @property
    def primary_text(self) -> str:
        """Best single text to send to the LLM: first non-empty section, or raw_text."""
        for text in self.sections.values():
            if text.strip():
                return text
        return self.raw_text


class FilingExtractor:
    def __init__(self, max_chars: int = _MAX_CHARS_DEFAULT) -> None:
        self._max_chars = max_chars

    def extract(self, form: str, html: str) -> FilingExtract:
        """Extract key sections from filing HTML.

        Returns a FilingExtract with sections keyed by item number.
        Never raises — returns empty FilingExtract on any failure.
        """
        if not html:
            return FilingExtract(form=form)
        try:
            text = _strip_html(html)
            text = text[: self._max_chars]
            sections = _extract_sections(form, text)
            return FilingExtract(form=form, sections=sections, raw_text=text)
        except Exception:
            return FilingExtract(form=form)


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&\w+;", " ", text)   # HTML entities
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_sections(form: str, text: str) -> dict[str, str]:
    """Split text at Item headings; return sections of interest for the given form."""
    items_wanted = set(_ITEMS_OF_INTEREST.get(form, []))
    if not items_wanted:
        return {}

    # Find all item positions in the text
    positions: list[tuple[str, int]] = []
    for match in _ITEM_PATTERN.finditer(text):
        item_id = match.group(1)
        positions.append((item_id, match.start()))

    sections: dict[str, str] = {}
    for i, (item_id, start) in enumerate(positions):
        if item_id not in items_wanted:
            continue
        end = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        content = text[start:end].strip()
        label = _section_label(form, item_id)
        sections[label] = content

    return sections


def _section_label(form: str, item_id: str) -> str:
    _labels = {
        ("8-K",   "2.02"): "results_of_operations",
        ("8-K",   "1.01"): "material_agreement",
        ("8-K",   "5.02"): "management_change",
        ("8-K",   "4.01"): "auditor_change",
        ("10-Q",  "2"):    "mda",
        ("10-K",  "7"):    "mda",
        ("SC 13D", "4"):   "purpose_of_transaction",
    }
    return _labels.get((form, item_id), f"item_{item_id}")
```

- [ ] **Step 4: Run tests — confirm 5 pass**

```
python -m pytest tests/unit/test_sec_filing_extractor.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```
git add research/src/sec/filing_extractor.py tests/unit/test_sec_filing_extractor.py
git commit -m "feat(sec-filing-agent): add FilingExtractor to pull key sections from 8-K/10-Q/10-K/SC13D

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## TICKET-SFA03: LLM Filing Analyst

**Description:** Build a `FilingAnalyst` that sends extracted filing text to the OpenAI API and returns a structured `FilingAnalysis` dict. Uses the existing `OpenAILlmReviewProvider` configuration pattern (`OPENAI_API_KEY`). If the API key is absent, returns a stub result with no LLM output — the filing is still recorded without crashing.

**Definition of Done:**
- `FilingAnalyst.analyze(filing, extract)` returns a `FilingAnalysis` with structured fields.
- When `OPENAI_API_KEY` is absent, returns a `FilingAnalysis` with `llm_available = False`.
- JSON output is valid and parseable; no raw LLM text is returned to callers.
- 4 unit tests pass (LLM mocked).

**Testing & QA:**
- Unit: `tests/unit/test_filing_analyst.py` (4 tests)
- Run: `python -m pytest tests/unit/test_filing_analyst.py -v`

**LLM Prompt Design (for the analyst):**

The prompt instructs the LLM to respond in strict JSON with these fields:

```json
{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": 0.0–1.0,
  "eps_vs_estimate": "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN",
  "revenue_vs_estimate": "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN",
  "guidance_change": "RAISED" | "LOWERED" | "MAINTAINED" | "NONE" | "UNKNOWN",
  "key_positives": ["...", "..."],   // max 3
  "key_risks": ["...", "..."],       // max 3
  "headline_sentence": "..."         // one sentence summary for the operator
}
```

---

- [ ] **Step 1: Write failing tests in `tests/unit/test_filing_analyst.py`**

```python
# tests/unit/test_filing_analyst.py
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sec.filing_extractor import FilingExtract
from sec.filing_monitor import AnnotatedFilingSummary
from fundamentals.filing_analyst import FilingAnalysis, FilingAnalyst


def _filing(form: str = "10-Q") -> AnnotatedFilingSummary:
    return AnnotatedFilingSummary(
        ticker="AAPL",
        cik="0000320193",
        accession_number="0001-test",
        filing_date="2024-11-01",
        report_date="2024-09-30",
        form=form,
        primary_document="aapl-10q-2024.htm",
    )


def _extract(text: str = "Revenue grew 8% year over year. EPS beat expectations.") -> FilingExtract:
    return FilingExtract(form="10-Q", sections={"mda": text}, raw_text=text)


def _mock_openai_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def test_analyze_returns_filing_analysis_with_required_fields() -> None:
    llm_json = json.dumps({
        "sentiment": "BULLISH",
        "confidence": 0.8,
        "eps_vs_estimate": "BEAT",
        "revenue_vs_estimate": "BEAT",
        "guidance_change": "RAISED",
        "key_positives": ["Revenue beat", "Services growth"],
        "key_risks": ["Margin pressure"],
        "headline_sentence": "Apple delivered a strong quarter with revenue and EPS beats.",
    })
    with patch("fundamentals.filing_analyst.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = {
            "choices": [{"message": {"content": llm_json}}]
        }
        analyst = FilingAnalyst(api_key="sk-test")
        result = analyst.analyze(_filing(), _extract())

    assert isinstance(result, FilingAnalysis)
    assert result.sentiment == "BULLISH"
    assert result.eps_vs_estimate == "BEAT"
    assert result.guidance_change == "RAISED"
    assert "Apple" in result.headline_sentence
    assert result.llm_available is True


def test_analyze_returns_stub_when_no_api_key() -> None:
    analyst = FilingAnalyst(api_key=None)
    result = analyst.analyze(_filing(), _extract())

    assert isinstance(result, FilingAnalysis)
    assert result.llm_available is False
    assert result.sentiment == "NEUTRAL"


def test_analyze_handles_malformed_llm_json() -> None:
    """If the LLM returns non-JSON text, returns a neutral stub without raising."""
    with patch("fundamentals.filing_analyst.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = {
            "choices": [{"message": {"content": "Sorry, I cannot help with that."}}]
        }
        analyst = FilingAnalyst(api_key="sk-test")
        result = analyst.analyze(_filing(), _extract())

    assert result.sentiment == "NEUTRAL"  # graceful fallback
    assert result.llm_available is True   # API was called, parse just failed


def test_analyze_to_dict_is_serializable() -> None:
    analyst = FilingAnalyst(api_key=None)
    result = analyst.analyze(_filing(), _extract())
    d = result.to_dict()

    import json
    serialized = json.dumps(d)  # must not raise
    loaded = json.loads(serialized)
    assert loaded["sentiment"] == "NEUTRAL"
```

- [ ] **Step 2: Run — confirm failure**

```
python -m pytest tests/unit/test_filing_analyst.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `research/src/fundamentals/filing_analyst.py`**

```python
# research/src/fundamentals/filing_analyst.py
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"   # cost-effective; upgrade to gpt-4o for higher quality

_SYSTEM_PROMPT = """You are a financial analyst reviewing SEC filings.
Respond ONLY with a single valid JSON object — no markdown, no commentary.
The JSON must have exactly these keys:
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL"
  confidence: float 0.0–1.0
  eps_vs_estimate: "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN"
  revenue_vs_estimate: "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN"
  guidance_change: "RAISED" | "LOWERED" | "MAINTAINED" | "NONE" | "UNKNOWN"
  key_positives: list of at most 3 short strings
  key_risks: list of at most 3 short strings
  headline_sentence: one sentence summary for an operator reviewing a trade candidate
"""


@dataclass
class FilingAnalysis:
    ticker: str
    form: str
    filing_date: str
    report_date: str | None
    sentiment: str = "NEUTRAL"
    confidence: float = 0.0
    eps_vs_estimate: str = "UNKNOWN"
    revenue_vs_estimate: str = "UNKNOWN"
    guidance_change: str = "UNKNOWN"
    key_positives: list[str] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    headline_sentence: str = ""
    llm_available: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def signal_score(self) -> float:
        """Map sentiment + confidence to a numeric score in [−1, +1] for the signal layer."""
        base = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}.get(self.sentiment, 0.0)
        return base * max(0.1, self.confidence)


class FilingAnalyst:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = MODEL,
        max_text_chars: int = 8_000,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._max_text_chars = max_text_chars

    def analyze(self, filing: Any, extract: Any) -> FilingAnalysis:
        """Analyze a filing extract and return structured FilingAnalysis.

        Never raises — returns a neutral stub if the LLM is unavailable or fails.
        """
        stub = FilingAnalysis(
            ticker=str(getattr(filing, "ticker", "")),
            form=str(getattr(filing, "form", "")),
            filing_date=str(getattr(filing, "filing_date", "")),
            report_date=getattr(filing, "report_date", None),
        )

        if not self._api_key or not self._api_key.startswith("sk-"):
            return stub

        stub.llm_available = True
        text = extract.primary_text[: self._max_text_chars]
        user_prompt = (
            f"Analyze this {filing.form} SEC filing for {filing.ticker} "
            f"(report date: {filing.report_date or filing.filing_date}):\n\n{text}"
        )

        try:
            raw = self._call_openai(user_prompt)
            return self._parse_response(raw, stub)
        except Exception:
            return stub

    def _call_openai(self, user_prompt: str) -> str:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                OPENAI_CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
        choices = resp.json().get("choices", [])
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", ""))

    def _parse_response(self, raw: str, stub: FilingAnalysis) -> FilingAnalysis:
        try:
            # Strip markdown code fences if present
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            parsed = json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            return stub  # graceful fallback

        stub.sentiment = str(parsed.get("sentiment", "NEUTRAL"))
        stub.confidence = float(parsed.get("confidence", 0.0))
        stub.eps_vs_estimate = str(parsed.get("eps_vs_estimate", "UNKNOWN"))
        stub.revenue_vs_estimate = str(parsed.get("revenue_vs_estimate", "UNKNOWN"))
        stub.guidance_change = str(parsed.get("guidance_change", "UNKNOWN"))
        stub.key_positives = [str(s) for s in (parsed.get("key_positives") or [])[:3]]
        stub.key_risks = [str(s) for s in (parsed.get("key_risks") or [])[:3]]
        stub.headline_sentence = str(parsed.get("headline_sentence", ""))
        return stub
```

- [ ] **Step 4: Run tests — confirm 4 pass**

```
python -m pytest tests/unit/test_filing_analyst.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```
git add research/src/fundamentals/filing_analyst.py tests/unit/test_filing_analyst.py
git commit -m "feat(sec-filing-agent): add LLM FilingAnalyst with structured JSON output

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## TICKET-SFA04: SEC Filing Signal

**Description:** Build `sec_filing_score()` that reads the stored filing analysis JSON and computes a signal score for the given ticker as of the given date. Register it as a new lane `sec_filing_analysis` in the live runtime config and lane promotion policies.

**Definition of Done:**
- `sec_filing_score(as_of, universe, loader)` returns `dict[str, float]` with scores in [−1, +1].
- The lane config is added to `research/src/live_runtime/config.py`.
- The lane promotion policy is added to `src/agency/runtime/lane_promotion.py`.
- 3 unit tests pass.

**Testing & QA:**
- Unit: `tests/unit/test_sec_filing_signal.py` (3 tests)
- Run: `python -m pytest tests/unit/test_sec_filing_signal.py -v`
- Integration: Restart the dev server and confirm "Sec Filing Analysis" appears in the lane health grid on `/signals` (may show 0 signals until a filing pull runs).

---

- [ ] **Step 1: Write failing tests in `tests/unit/test_sec_filing_signal.py`**

```python
# tests/unit/test_sec_filing_signal.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from signals.sec_filing import SecFilingLoader, sec_filing_score


@dataclass
class _FakeFilingLoader:
    _analyses: dict[str, list[dict]]

    def latest_filing_analyses(
        self, ticker: str, as_of: date, n: int = 3
    ) -> list[dict]:
        return self._analyses.get(ticker.upper(), [])


def test_bullish_filing_produces_positive_score() -> None:
    loader = _FakeFilingLoader({
        "AAPL": [
            {"sentiment": "BULLISH", "confidence": 0.85, "filing_date": "2024-11-01",
             "eps_vs_estimate": "BEAT", "guidance_change": "RAISED"},
        ]
    })

    scores = sec_filing_score(date(2024, 11, 15), {"AAPL"}, loader)

    assert "AAPL" in scores
    assert scores["AAPL"] > 0


def test_bearish_filing_produces_negative_score() -> None:
    loader = _FakeFilingLoader({
        "MSFT": [
            {"sentiment": "BEARISH", "confidence": 0.7, "filing_date": "2024-11-01",
             "eps_vs_estimate": "MISS", "guidance_change": "LOWERED"},
        ]
    })

    scores = sec_filing_score(date(2024, 11, 15), {"MSFT"}, loader)

    assert scores["MSFT"] < 0


def test_missing_ticker_excluded_from_scores() -> None:
    loader = _FakeFilingLoader({})  # no data for AMZN

    scores = sec_filing_score(date(2024, 11, 15), {"AMZN"}, loader)

    assert "AMZN" not in scores
```

- [ ] **Step 2: Create `research/src/signals/sec_filing.py`**

```python
# research/src/signals/sec_filing.py
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol


class SecFilingLoader(Protocol):
    def latest_filing_analyses(
        self, ticker: str, as_of: date, n: int = 3
    ) -> list[dict]: ...


def sec_filing_score(
    as_of: date,
    universe: Iterable[str],
    loader: SecFilingLoader,
) -> dict[str, float]:
    """Return a score per ticker from the most recent filing analysis.

    Score is in [−1, +1]: positive = bullish, negative = bearish.
    Returns only tickers with available analysis.
    """
    scores: dict[str, float] = {}
    for ticker in {t.upper() for t in universe}:
        analyses = loader.latest_filing_analyses(ticker, as_of, n=3)
        if not analyses:
            continue
        score = _aggregate_score(analyses)
        if score is not None:
            scores[ticker] = score
    return scores


def _aggregate_score(analyses: list[dict]) -> float | None:
    """Weighted average of signal_score across analyses, most recent weighted highest."""
    if not analyses:
        return None
    total = 0.0
    weight_sum = 0.0
    for i, analysis in enumerate(reversed(analyses)):  # most recent first
        weight = 1.0 / (2 ** i)                        # exponential decay: 1, 0.5, 0.25
        base = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}.get(
            str(analysis.get("sentiment", "NEUTRAL")), 0.0
        )
        confidence = float(analysis.get("confidence", 0.5))
        total += base * confidence * weight
        weight_sum += weight
    return total / weight_sum if weight_sum > 0 else None
```

- [ ] **Step 3: Add `sec_filing_analysis` to `LANE_CONFIGS` in `research/src/live_runtime/config.py`**

Find `LANE_CONFIGS` and add after the last entry:

```python
    "sec_filing_analysis": RuntimeLaneConfig(
        "sec_filing_analysis",
        DatasetName.SEC_FILINGS,
        "sec-edgar-filings",
        "OFFICIAL_FILING",
        "CONFIRMED",
        FreshnessDomain.SEC_FUNDAMENTALS,
        0.75,
    ),
```

Also add `SEC_FILINGS = "sec_filings"` to `DatasetName` in `research/src/pit/manifest.py`.

- [ ] **Step 4: Add `sec_filing_analysis` to `LANE_PROMOTION_POLICIES` in `src/agency/runtime/lane_promotion.py`**

```python
    "sec_filing_analysis": LanePromotionPolicy(
        "sec_filing_analysis",
        ACTION_WEIGHTED,
        "Can contribute to WATCH when a recent filing with clear sentiment is available.",
        "At least one SEC filing analyzed within the last 90 days.",
        (
            "Official SEC filings are the most reliable forward-looking signal available. "
            "LLM-extracted guidance and surprise data directly informs the trade decision."
        ),
    ),
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/unit/test_sec_filing_signal.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```
git add research/src/signals/sec_filing.py research/src/live_runtime/config.py research/src/pit/manifest.py src/agency/runtime/lane_promotion.py tests/unit/test_sec_filing_signal.py
git commit -m "feat(sec-filing-agent): add sec_filing_analysis signal lane and scoring

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## TICKET-SFA05: Pull Script + Scheduler Integration

**Description:** Create `run_sec_filing_monitor.py` that: (1) loads the universe tickers + CIK map; (2) checks EDGAR for new filings since last checkpoint; (3) fetches and extracts each new filing; (4) runs LLM analysis; (5) stores analysis JSON; (6) updates the checkpoint. Register this as a scheduled job.

**Definition of Done:**
- `python research/scripts/run_sec_filing_monitor.py --dry-run` prints new filings without writing.
- `python research/scripts/run_sec_filing_monitor.py` processes new filings end-to-end.
- Analysis JSONs written to `research/data/state/sec_filings/analyses/{TICKER}/{accession}.json`.
- On second run (no new filings), prints "No new filings since {date}." and exits 0.

**Testing & QA:**
- Manual smoke test: `python research/scripts/run_sec_filing_monitor.py --dry-run --tickers AAPL MSFT`
- Verify checkpoint written: `cat research/data/state/sec_filings/checkpoint.json`
- Verify analyses stored: `ls research/data/state/sec_filings/analyses/AAPL/`

---

- [ ] **Step 1: Create `research/scripts/run_sec_filing_monitor.py`**

```python
#!/usr/bin/env python3
# research/scripts/run_sec_filing_monitor.py
"""Run the SEC filing monitor: detect new filings, analyze, store results.

Usage:
    python run_sec_filing_monitor.py --tickers AAPL MSFT NVDA
    python run_sec_filing_monitor.py --dry-run
    python run_sec_filing_monitor.py  # uses checkpoint; processes universe
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "research" / "src"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from sec.cik import cik_lookup_for_tickers, parse_company_tickers
from sec.client import SecClient, SecClientConfig
from sec.filing_extractor import FilingExtractor
from sec.filing_monitor import FilingCheckpoint, FilingMonitor

ANALYSES_DIR = REPO_ROOT / "research" / "data" / "state" / "sec_filings" / "analyses"
CHECKPOINT_PATH = REPO_ROOT / "research" / "data" / "state" / "sec_filings" / "checkpoint.json"
DEFAULT_LOOKBACK_DAYS = 7


async def main(args: argparse.Namespace) -> int:
    # ── Load CIK map from EDGAR company_tickers.json ─────────────────────────
    config = SecClientConfig(
        user_agent=os.environ.get("SEC_USER_AGENT", "trading-agency dev@example.com")
    )
    async with SecClient(config) as client:
        raw_tickers = await client.get_json("https://www.sec.gov/files/company_tickers.json")
        cik_mapping = parse_company_tickers(raw_tickers)

    tickers = args.tickers or _load_universe()
    matched, missing = cik_lookup_for_tickers(tickers, cik_mapping)

    if missing:
        for t in missing:
            print(f"  WARN: no CIK for {t}")

    cik_map = {ticker: info.cik for ticker, info in matched.items()}

    # ── Determine since date ─────────────────────────────────────────────────
    checkpoint = FilingCheckpoint(path=CHECKPOINT_PATH)
    since = checkpoint.load() or (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    print(f"Checking for new filings since {since} for {len(cik_map)} ticker(s)...")

    # ── Detect new filings ───────────────────────────────────────────────────
    async with SecClient(config) as client:
        monitor = FilingMonitor(client=client, cik_map=cik_map)
        new_filings = await monitor.check_new_filings(list(cik_map.keys()), since=since)

    if not new_filings:
        print(f"No new filings since {since}.")
        if not args.dry_run:
            checkpoint.save(date.today())
        return 0

    print(f"Found {len(new_filings)} new filing(s):")
    for f in new_filings:
        print(f"  {f.ticker} {f.form} filed {f.filing_date} → {f.accession_number}")

    if args.dry_run:
        print("(dry run — not fetching or analyzing)")
        return 0

    # ── Fetch, extract, and analyze each filing ──────────────────────────────
    from fundamentals.filing_analyst import FilingAnalyst
    extractor = FilingExtractor()
    analyst = FilingAnalyst()

    async with SecClient(config) as client:
        for filing in new_filings:
            try:
                html = await client.get_text(filing.document_url)
                extract = extractor.extract(filing.form, html)
                analysis = analyst.analyze(filing, extract)

                out_dir = ANALYSES_DIR / filing.ticker
                out_dir.mkdir(parents=True, exist_ok=True)
                accession_safe = filing.accession_number.replace("/", "-")
                out_path = out_dir / f"{accession_safe}.json"
                out_path.write_text(
                    json.dumps(analysis.to_dict(), indent=2, default=str),
                    encoding="utf-8",
                )
                sentiment_label = "✓" if analysis.sentiment == "BULLISH" else (
                    "✗" if analysis.sentiment == "BEARISH" else "="
                )
                print(f"  {sentiment_label} {filing.ticker} {filing.form} [{analysis.sentiment}] — {analysis.headline_sentence[:80]}")

            except Exception as exc:
                print(f"  ERR {filing.ticker} {filing.form}: {exc}", file=sys.stderr)

    checkpoint.save(date.today())
    print(f"\nCheckpoint updated to {date.today()}.")
    return 0


def _load_universe() -> list[str]:
    universe_path = REPO_ROOT / "research" / "data" / "universe.txt"
    if universe_path.is_file():
        return [line.strip().upper() for line in universe_path.read_text().splitlines() if line.strip()]
    return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SEC filing monitor.")
    parser.add_argument("--tickers", nargs="*", help="Override tickers (default: universe).")
    parser.add_argument("--dry-run", action="store_true", help="Detect only; don't fetch or analyze.")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
```

- [ ] **Step 2: Ensure `SecClient` has `get_text()` method**

Check `research/src/sec/client.py`. The file has `get_json()` and `get_text()` (confirmed at line 97). If `get_text()` is missing, add it beside `get_json()`:

```python
async def get_text(self, url: str) -> str:
    """GET ``url`` and return response body as a string."""
    await self._rate_limiter.wait()
    resp = await self._client.get(url)
    resp.raise_for_status()
    return resp.text
```

- [ ] **Step 3: Add `SEC_USER_AGENT` to `.env.example`**

```
SEC_USER_AGENT=trading-agency your@email.com   # required by SEC EDGAR; must identify app and contact
```

- [ ] **Step 4: Smoke test**

```
python research/scripts/run_sec_filing_monitor.py --dry-run --tickers AAPL MSFT
```

Expected output (example):
```
Checking for new filings since 2026-05-23 for 2 ticker(s)...
Found 2 new filing(s):
  AAPL 10-Q filed 2026-05-02 → 0000320193-26-000050
  MSFT 10-Q filed 2026-05-07 → 0000789019-26-000022
(dry run — not fetching or analyzing)
```

- [ ] **Step 5: Commit**

```
git add research/scripts/run_sec_filing_monitor.py .env.example
git commit -m "feat(sec-filing-agent): add run_sec_filing_monitor.py pull script

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## TICKET-SFA06: Evidence Display — Filing Analysis Inspect Panel

**Description:** Add `_sec_filing_evidence()` to `signal_evidence.py` so that the signals page Inspect panel shows the LLM analysis headline, sentiment, EPS/revenue surprise, guidance change, and key points for a `sec_filing_analysis` signal row.

**Definition of Done:**
- `_sec_filing_evidence()` is registered in the `builders` dict in `_evidence_for_row()`.
- The inspect panel shows 6 cards: Sentiment, EPS vs. Estimate, Revenue vs. Estimate, Guidance Change, Key Positive, Key Risk.
- `trigger_headline` includes the form type, filing date, and headline sentence from the LLM.
- 2 unit tests pass.

**Testing & QA:**
- Unit: extend `tests/unit/test_signal_evidence_fundamentals.py` with 2 tests in a new class.
- Visual QA: Run the app, navigate to `/signals`, find a `sec_filing_analysis` row, click Inspect — verify the cards appear correctly.

**UX Specification:**
- Card 1: Sentiment — value = "BULLISH" / "BEARISH" / "NEUTRAL", tone = pass/block/neutral
- Card 2: EPS vs. Estimate — value = "BEAT" / "MISS" / "IN_LINE" / "UNKNOWN", tone = same mapping
- Card 3: Revenue vs. Estimate — same
- Card 4: Guidance Change — value = "RAISED" / "LOWERED" / "MAINTAINED" / "NONE", tone = pass for raised, block for lowered, neutral otherwise
- Card 5: Key Positive — first item from `key_positives`, tone = "pass"
- Card 6: Key Risk — first item from `key_risks`, tone = "warn"

**Design Specification:**
- `trigger_headline`: `"{ticker} {form} filed {date} — {headline_sentence}"`
- `trigger_detail`: `"LLM analysis of the SEC filing text. Score confidence: {confidence}. Source: SEC EDGAR official filing."`

---

- [ ] **Step 1: Write 2 failing tests (append to `tests/unit/test_signal_evidence_fundamentals.py`)**

```python
# append to tests/unit/test_signal_evidence_fundamentals.py

def test_sec_filing_evidence_includes_sentiment_card() -> None:
    from agency.runtime.signal_evidence import _sec_filing_evidence

    row = {"ticker": "AAPL", "lane_key": "sec_filing_analysis"}
    detail = {
        "sentiment": "BULLISH",
        "confidence": 0.8,
        "eps_vs_estimate": "BEAT",
        "revenue_vs_estimate": "BEAT",
        "guidance_change": "RAISED",
        "key_positives": ["Revenue beat estimates", "Services growth"],
        "key_risks": ["Margin pressure from FX"],
        "headline_sentence": "Strong quarter with beats across the board.",
        "filing_form": "10-Q",
        "filing_date": "2024-11-01",
    }
    result = _sec_filing_evidence(row, detail, date(2024, 11, 15))

    card_labels = [c["label"] for c in result["trigger_cards"]]
    assert "Sentiment" in card_labels
    assert "EPS vs. estimate" in card_labels or any("EPS" in l for l in card_labels)

    sentiment_card = next(c for c in result["trigger_cards"] if c["label"] == "Sentiment")
    assert sentiment_card["tone"] == "pass"  # BULLISH → pass


def test_sec_filing_evidence_bearish_gives_block_tone() -> None:
    from agency.runtime.signal_evidence import _sec_filing_evidence

    row = {"ticker": "MSFT", "lane_key": "sec_filing_analysis"}
    detail = {
        "sentiment": "BEARISH",
        "confidence": 0.7,
        "eps_vs_estimate": "MISS",
        "revenue_vs_estimate": "MISS",
        "guidance_change": "LOWERED",
        "key_positives": [],
        "key_risks": ["Revenue miss", "Guidance lowered"],
        "headline_sentence": "Disappointing quarter with guidance cut.",
        "filing_form": "10-Q",
        "filing_date": "2024-11-01",
    }
    result = _sec_filing_evidence(row, detail, date(2024, 11, 15))

    sentiment_card = next(c for c in result["trigger_cards"] if c["label"] == "Sentiment")
    assert sentiment_card["tone"] == "block"  # BEARISH → block
```

- [ ] **Step 2: Add `_sec_filing_evidence()` to `src/agency/runtime/signal_evidence.py`**

Add the function after `_fundamentals_evidence()`:

```python
def _sec_filing_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    sentiment = _text(detail.get("sentiment"), "NEUTRAL")
    filing_form = _text(detail.get("filing_form"), "filing")
    filing_date = _text(detail.get("filing_date"), "unknown")
    headline_sentence = _text(detail.get("headline_sentence"), "SEC filing analyzed.")
    confidence = _float(detail.get("confidence"))
    positives = detail.get("key_positives") or []
    risks = detail.get("key_risks") or []
    first_positive = str(positives[0]) if positives else "n/a"
    first_risk = str(risks[0]) if risks else "n/a"

    def _sentiment_tone(s: str) -> str:
        return {"BULLISH": "pass", "BEARISH": "block"}.get(s.upper(), "neutral")

    def _surprise_tone(s: str) -> str:
        return {"BEAT": "pass", "MISS": "block"}.get(s.upper(), "neutral")

    def _guidance_tone(s: str) -> str:
        return {"RAISED": "pass", "LOWERED": "block"}.get(s.upper(), "neutral")

    return _detail_payload(
        row,
        as_of,
        headline=f"{row['ticker']} {filing_form} filed {filing_date} — {headline_sentence}",
        detail=(
            f"LLM analysis of the official SEC {filing_form} filing text. "
            f"Score confidence: {_pct(confidence)}. "
            "Source: SEC EDGAR official filing."
        ),
        cards=[
            _card("Sentiment",            sentiment,
                  "Overall tone of the filing.",
                  _sentiment_tone(sentiment)),
            _card("EPS vs. estimate",      _text(detail.get("eps_vs_estimate"), "UNKNOWN"),
                  "Actual EPS vs. analyst consensus at time of filing.",
                  _surprise_tone(_text(detail.get("eps_vs_estimate"), ""))),
            _card("Revenue vs. estimate",  _text(detail.get("revenue_vs_estimate"), "UNKNOWN"),
                  "Actual revenue vs. analyst consensus.",
                  _surprise_tone(_text(detail.get("revenue_vs_estimate"), ""))),
            _card("Guidance",              _text(detail.get("guidance_change"), "UNKNOWN"),
                  "Whether the company raised, maintained, or lowered guidance.",
                  _guidance_tone(_text(detail.get("guidance_change"), ""))),
            _card("Key positive",          first_positive,
                  "Top positive factor extracted from the filing.",
                  "pass" if first_positive != "n/a" else "neutral"),
            _card("Key risk",              first_risk,
                  "Top risk factor extracted from the filing.",
                  "warn" if first_risk != "n/a" else "neutral"),
        ],
    )
```

Register it in the `builders` dict in `_evidence_for_row()`:

```python
    builders = {
        "abnormal_volume":      _abnormal_volume_evidence,
        "technical_analysis":   _technical_analysis_evidence,
        "fundamentals":         _fundamentals_evidence,
        "insider":              _insider_evidence,
        "institutional":        _institutional_evidence,
        "news":                 _news_evidence,
        "sec_filing_analysis":  _sec_filing_evidence,    # ← add this line
    }
```

- [ ] **Step 3: Run all tests**

```
python -m pytest tests/unit/test_signal_evidence_fundamentals.py -v
```

Expected: 5 PASSED (3 from FA07 + 2 new).

- [ ] **Step 4: Commit**

```
git add src/agency/runtime/signal_evidence.py tests/unit/test_signal_evidence_fundamentals.py
git commit -m "feat(sec-filing-agent): add SEC filing evidence panel to signals inspect view

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## TICKET-SFA07: Scheduler Integration

**Description:** Register `run_sec_filing_monitor.py` as a scheduled job in the data refresh pipeline so it runs automatically: daily at 06:00 ET on weekdays (before market open), and on-demand when triggered manually.

**Definition of Done:**
- A scheduled job definition exists in `research/src/data_refresh/jobs.py` for `sec_filing_analysis`.
- `sec_filing_analysis` appears in the "signal lanes" section of the command page (live config).
- Manual trigger via POST `/refresh/sec_filing_analysis` works.

**Testing & QA:**
- Unit: check `research/src/data_refresh/jobs.py` has a `_sec_filing_job()` function.
- Integration: Run `python research/scripts/run_sec_filing_monitor.py --dry-run` successfully in the scheduler context.
- Manual: On the command page, the `sec_filing_analysis` lane shows "Not configured" or "Configured" based on `OPENAI_API_KEY` presence.

---

- [ ] **Step 1: Add a `_sec_filing_job()` function to `research/src/data_refresh/jobs.py`**

Find the pattern for other job functions (e.g., `_company_facts_job`) and add:

```python
def _sec_filing_job(
    config: RefreshBatchConfig,
    reasons: list[str],
) -> RefreshJob | None:
    """Build a job to run the SEC filing monitor."""
    command = _base_command(config, "run_sec_filing_monitor.py")
    return _job(config, "sec_filing_analysis", command, reasons)
```

Add it to the `JOBS` mapping dict in the same file:
```python
"sec_filing_analysis": _sec_filing_job,
```

- [ ] **Step 2: Add `SEC_FILING_ANALYSIS` to `SUPPORT_LANES` in `src/agency/runtime/data_load_status.py`**

Find:
```python
SUPPORT_LANES = {"fundamentals", "insider", "institutional"}
```

Change to:
```python
SUPPORT_LANES = {"fundamentals", "insider", "institutional", "sec_filing_analysis"}
```

- [ ] **Step 3: Run full test suite to confirm no regressions**

```
python -m pytest tests/unit/ -q --tb=short 2>&1 | tail -10
```

Expected: all pass (same count as before this ticket, plus the new tests from earlier tickets).

- [ ] **Step 4: Commit**

```
git add research/src/data_refresh/jobs.py src/agency/runtime/data_load_status.py
git commit -m "feat(sec-filing-agent): wire sec_filing_analysis into scheduler and command page

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Acceptance Criteria — SEC Filing Analysis Agent

| AC | Verification |
|---|---|
| Filing monitor detects new 8-K/10-Q/10-K/SC 13D | `test_sec_filing_monitor.py` — 4 pass |
| Section extractor pulls MD&A, Item 2.02, Purpose | `test_sec_filing_extractor.py` — 5 pass |
| LLM analyst returns structured JSON | `test_filing_analyst.py` — 4 pass |
| No crash when OPENAI_API_KEY absent | `test_filing_analyst.py::test_analyze_returns_stub_when_no_api_key` |
| Signal score is positive for BULLISH, negative for BEARISH | `test_sec_filing_signal.py` — 3 pass |
| Lane appears in LANE_CONFIGS | `live_runtime/config.py` — inspect manually |
| Inspect panel shows 6 cards with correct tones | `test_signal_evidence_fundamentals.py` — 2 new pass |
| Dry run prints new filings without writing files | Manual smoke test |
| All original tests still pass | `python -m pytest tests/unit/ -q` — no regressions |

---

## Environment Variables Required

Add all to `.env.example`:

```bash
# SEC Filing Analysis Agent
OPENAI_API_KEY=sk-...     # Required for LLM analysis; without it, filings are stored raw only
SEC_USER_AGENT=trading-agency your@email.com  # Required by SEC EDGAR ToS
```
