from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Protocol

from sec.client import archive_url
from sec.submissions import FilingSummary

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, instrumented_call


class FilingDocumentClient(Protocol):
    async def filing_index(self, cik: str, accession_number: str) -> Mapping[str, Any]: ...

    async def get_text(self, url: str) -> str: ...


async def info_table_documents(
    client: FilingDocumentClient,
    filing: FilingSummary,
) -> list[str]:
    index = await client.filing_index(filing.cik, filing.accession_number)
    directory = index.get("directory")
    if not isinstance(directory, Mapping):
        return []
    items = directory.get("item")
    if not isinstance(items, list):
        return []
    documents: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", ""))
        item_type = str(item.get("type", "")).lower()
        if _is_information_table_xml(
            name=name,
            item_type=item_type,
            primary_document=filing.primary_document,
        ):
            documents.append(name)
    return documents


def _is_information_table_xml(
    *,
    name: str,
    item_type: str,
    primary_document: str,
) -> bool:
    document_name = PurePosixPath(name).name.lower()
    primary_name = PurePosixPath(primary_document).name.lower()
    if not document_name.endswith(".xml"):
        return False
    if document_name in {primary_name, "primary_doc.xml"}:
        return False
    del item_type
    return True


async def fetch_document(
    client: FilingDocumentClient,
    filing: FilingSummary,
    document: str,
    clock: Callable[[], datetime],
) -> str:
    url = archive_url(filing.cik, filing.accession_number, document)

    async def call() -> str:
        return await client.get_text(url)

    wrapped = await instrumented_call(
        call,
        source="sec_edgar",
        source_tier=SourceTier.OFFICIAL_FILING,
        source_id=f"13f:{filing.accession_number}:{document}",
        verification_level=VerificationLevel.CONFIRMED,
        freshness_domain=FreshnessDomain.SEC_13F,
        timestamp_as_of=clock(),
        confidence=1.0,
        source_url=url,
        clock=clock,
    )
    return wrapped.value
