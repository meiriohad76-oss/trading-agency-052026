from __future__ import annotations

from datetime import UTC, date, datetime

from agency.provenance import SourceTier, VerificationLevel


def parse_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(str(value).replace(",", ""))


def parse_int(value: object) -> int | None:
    parsed = parse_float(value)
    return None if parsed is None else int(parsed)


def cik_string(value: int | str) -> str:
    return str(value).zfill(10)


def accession_nodash(accession_number: str) -> str:
    return accession_number.replace("-", "")


def utc_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def provenance_columns(
    *,
    source_id: str,
    source_url: str,
    filing_date: date,
    fetched_at: datetime,
) -> dict[str, object]:
    return {
        "source": "sec_edgar",
        "source_tier": SourceTier.OFFICIAL_FILING.value,
        "source_id": source_id,
        "source_url": source_url,
        "timestamp_observed": utc_datetime(fetched_at),
        "timestamp_as_of": filing_date,
        "freshness": "STALE",
        "confidence": 1.0,
        "verification_level": VerificationLevel.CONFIRMED.value,
    }
