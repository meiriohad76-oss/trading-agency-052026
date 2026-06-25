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
