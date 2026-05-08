from __future__ import annotations

from typing import Any

from sec.form13f_documents import info_table_documents
from sec.submissions import FilingSummary


async def test_info_table_documents_include_numeric_sec_xml_attachment() -> None:
    documents = await info_table_documents(
        _FakeDocumentClient(
            [
                {"name": "primary_doc.xml", "type": "text.gif"},
                {"name": "46994.xml", "type": "text.gif"},
                {"name": "0001193125-25-282901.txt", "type": "text.gif"},
            ]
        ),
        _filing(),
    )

    assert documents == ["46994.xml"]


async def test_info_table_documents_include_named_holdings_attachment() -> None:
    documents = await info_table_documents(
        _FakeDocumentClient(
            [
                {"name": "primary_doc.xml", "type": "text.gif"},
                {"name": "renaissance13Fq32025_holding.xml", "type": "text.gif"},
            ]
        ),
        _filing(),
    )

    assert documents == ["renaissance13Fq32025_holding.xml"]


async def test_info_table_documents_include_accession_named_attachment() -> None:
    documents = await info_table_documents(
        _FakeDocumentClient(
            [
                {"name": "primary_doc.xml", "type": "text.gif"},
                {"name": "0000950123-22-002973-9815.xml", "type": "text.gif"},
            ]
        ),
        _filing(),
    )

    assert documents == ["0000950123-22-002973-9815.xml"]


class _FakeDocumentClient:
    def __init__(self, items: list[dict[str, str]]) -> None:
        self._items = items

    async def filing_index(self, cik: str, accession_number: str) -> dict[str, Any]:
        del cik, accession_number
        return {"directory": {"item": self._items}}

    async def get_text(self, url: str) -> str:
        raise AssertionError(url)


def _filing() -> FilingSummary:
    return FilingSummary(
        cik="0001067983",
        accession_number="0001193125-25-282901",
        filing_date="2025-11-14",
        report_date="2025-09-30",
        form="13F-HR",
        primary_document="primary_doc.xml",
    )
