from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree


@dataclass(frozen=True)
class FeedSpec:
    url: str
    source_name: str
    ticker: str | None = None


def parse_rss(xml: str, *, feed: FeedSpec, fetched_at: datetime) -> list[dict[str, object]]:
    root = ElementTree.fromstring(xml)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    return [
        row
        for item in items
        if (row := _item_row(item, feed=feed, fetched_at=fetched_at)) is not None
    ]


def _item_row(
    item: ElementTree.Element,
    *,
    feed: FeedSpec,
    fetched_at: datetime,
) -> dict[str, object] | None:
    title = _text(item, "title")
    url = _link(item)
    if title is None or url is None:
        return None
    published = _published_at(item) or fetched_at
    return {
        "ticker": None if feed.ticker is None else feed.ticker.upper(),
        "feed_url": feed.url,
        "feed_name": feed.source_name,
        "title": title,
        "url": url,
        "summary": _text(item, "description") or _text(item, "summary"),
        "published_at": published,
    }


def _text(item: ElementTree.Element, name: str) -> str | None:
    values = [
        child.text
        for child in item.iter()
        if _local_name(child.tag) == name and child.text is not None
    ]
    if not values:
        return None
    parsed = values[0].strip()
    return parsed or None


def _link(item: ElementTree.Element) -> str | None:
    text_link = _text(item, "link")
    if text_link is not None:
        return text_link
    for child in item.iter():
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href")
            if href:
                return href
    return None


def _published_at(item: ElementTree.Element) -> datetime | None:
    raw = _text(item, "pubDate") or _text(item, "published") or _text(item, "updated")
    if raw is None:
        return None
    for parser in (_parse_rfc2822, _parse_iso):
        parsed = parser(raw)
        if parsed is not None:
            return parsed
    return None


def _parse_rfc2822(raw: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return _ensure_utc(parsed)


def _parse_iso(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
