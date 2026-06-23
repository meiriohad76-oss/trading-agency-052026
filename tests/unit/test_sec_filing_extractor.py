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
