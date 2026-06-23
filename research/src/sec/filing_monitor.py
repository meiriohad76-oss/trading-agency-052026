from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sec.client import SecClient, archive_url
from sec.submissions import FilingSummary, parse_recent_filings

FORMS_OF_INTEREST: frozenset[str] = frozenset({"8-K", "10-Q", "10-K", "SC 13D"})

DEFAULT_CHECKPOINT_PATH = (
    Path(__file__).resolve().parents[3] /
    "data" / "state" / "sec_filings" / "checkpoint.json"
)


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
        return archive_url(self.cik, self.accession_number, self.primary_document)


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
        cik_map: dict[str, str],
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
        """Return filings for tickers with filing_date >= since."""
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
                forms=set(self._forms),
                start_date=since.isoformat(),
            )
            for s in summaries:
                results.append(
                    AnnotatedFilingSummary(
                        ticker=ticker.upper(),
                        cik=s.cik,
                        accession_number=s.accession_number,
                        filing_date=s.filing_date,
                        report_date=s.report_date,
                        form=s.form,
                        primary_document=s.primary_document,
                    )
                )
        return results
