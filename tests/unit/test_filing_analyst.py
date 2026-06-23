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
