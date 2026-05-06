from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import cast

import polars as pl

from agency.provenance import (
    FreshnessStatus,
    Provenance,
    Provenanced,
    SourceTier,
    VerificationLevel,
)

from .exceptions import DataNotAvailableAt

PROVENANCE_COLUMNS = frozenset(
    {
        "source",
        "source_tier",
        "source_id",
        "source_url",
        "timestamp_observed",
        "timestamp_as_of",
        "freshness",
        "confidence",
        "verification_level",
    }
)


class ProvenancedTickerSet(set[str]):
    def __init__(self, values: Iterable[str], provenance: Provenance) -> None:
        super().__init__(values)
        self.provenance = provenance


def rows(frame: pl.DataFrame) -> list[Mapping[str, object]]:
    return cast(list[Mapping[str, object]], frame.to_dicts())


def row_to_provenanced(
    row: Mapping[str, object],
    *,
    exclude: set[str],
) -> Provenanced[dict[str, object]]:
    payload = {
        key: value
        for key, value in row.items()
        if key not in PROVENANCE_COLUMNS and key not in exclude and not key.startswith("__")
    }
    return Provenanced[dict[str, object]](value=payload, provenance=provenance_from_row(row))


def provenance_from_row(row: Mapping[str, object]) -> Provenance:
    return Provenance(
        source=str(_required(row, "source")),
        source_tier=SourceTier(str(_required(row, "source_tier"))),
        source_id=str(_required(row, "source_id")),
        source_url=_optional_str(row.get("source_url")),
        timestamp_observed=as_utc_datetime(_required(row, "timestamp_observed")),
        timestamp_as_of=as_utc_datetime(_required(row, "timestamp_as_of")),
        freshness=FreshnessStatus(str(_required(row, "freshness"))),
        confidence=_required_float(row, "confidence"),
        verification_level=VerificationLevel(str(_required(row, "verification_level"))),
    )


def as_utc_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = date_to_utc(value)
    else:
        raw = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def date_to_utc(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _required(row: Mapping[str, object], key: str) -> object:
    if key not in row or row[key] is None:
        raise DataNotAvailableAt("provenance", None, f"missing column {key}")
    return row[key]


def _required_float(row: Mapping[str, object], key: str) -> float:
    value = _required(row, key)
    if not isinstance(value, int | float | str):
        raise DataNotAvailableAt("provenance", None, f"{key} must be numeric")
    return float(value)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
