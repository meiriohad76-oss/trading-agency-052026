from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any

import pandas as pd

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, compute_freshness

DEFAULT_SOURCE = "local-activity-alerts"
DEFAULT_SOURCE_TIER = SourceTier.PAID_SUB_EMAIL.value
DEFAULT_VERIFICATION = VerificationLevel.CONFIRMED.value
DEFAULT_CONFIDENCE = 0.8
REQUIRED_COLUMNS = frozenset({"ticker", "alert_type", "direction", "observed_at"})


def read_activity_alert_csv(
    path: Path,
    *,
    fetched_at: datetime,
    default_source: str = DEFAULT_SOURCE,
) -> pd.DataFrame:
    raw = pd.read_csv(path)
    _require_columns(raw)
    rows = [
        _normalize_row(_string_keyed(row), fetched_at=fetched_at, default_source=default_source)
        for row in raw.to_dict(orient="records")
    ]
    return pd.DataFrame(rows)


def _normalize_row(
    row: dict[str, object],
    *,
    fetched_at: datetime,
    default_source: str,
) -> dict[str, object]:
    observed_at = _timestamp(row["observed_at"])
    event_time = _timestamp(row.get("event_time") or row["observed_at"])
    source = _text(row.get("source")) or default_source
    source_id = _text(row.get("source_id")) or _source_id(source, row, observed_at)
    tier = _enum_text(row.get("source_tier")) or DEFAULT_SOURCE_TIER
    verification = _enum_text(row.get("verification_level")) or DEFAULT_VERIFICATION
    confidence = _number(row.get("confidence"), DEFAULT_CONFIDENCE)
    confidence_value = DEFAULT_CONFIDENCE if confidence is None else confidence
    return {
        "ticker": str(row["ticker"]).upper().strip(),
        "alert_type": _alert_type(str(row["alert_type"])),
        "direction": _direction(str(row["direction"])),
        "event_time": event_time.isoformat(),
        "summary": _text(row.get("summary")),
        "price": _number(row.get("price")),
        "volume": _number(row.get("volume")),
        "notional": _number(row.get("notional")),
        "premium": _number(row.get("premium")),
        "source": source,
        "source_tier": SourceTier(tier).value,
        "source_id": source_id,
        "source_url": _text(row.get("source_url")),
        "timestamp_observed": observed_at.isoformat(),
        "timestamp_as_of": observed_at.isoformat(),
        "freshness": compute_freshness(observed_at, FreshnessDomain.NEWS, now=fetched_at).value,
        "confidence": min(1.0, max(0.0, confidence_value)),
        "verification_level": VerificationLevel(verification).value,
    }


def _require_columns(frame: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(f"activity alert CSV missing columns: {missing}")


def _string_keyed(row: dict[Any, Any]) -> dict[str, object]:
    return {str(key): value for key, value in row.items()}


def _timestamp(value: object) -> datetime:
    parsed = pd.Timestamp(str(value)).to_pydatetime()
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(value: object) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _enum_text(value: object) -> str | None:
    text = _text(value)
    return None if text is None else text.upper()


def _number(value: object, default: float | None = None) -> float | None:
    if _is_missing(value):
        return default
    try:
        return float(str(value))
    except ValueError:
        return default


def _alert_type(value: str) -> str:
    return value.lower().strip().replace(" ", "_").replace("-", "_")


def _direction(value: str) -> str:
    normalized = value.upper().strip()
    aliases = {
        "BUY": "BULLISH",
        "CALL": "BULLISH",
        "LONG": "BULLISH",
        "SELL": "BEARISH",
        "PUT": "BEARISH",
        "SHORT": "BEARISH",
    }
    return aliases.get(normalized, normalized)


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, Real) and not isinstance(value, bool):
        return math.isnan(float(value))
    return False


def _source_id(source: str, row: dict[str, object], observed_at: datetime) -> str:
    digest = hashlib.sha256()
    for value in (
        source,
        str(row.get("ticker", "")),
        str(row.get("alert_type", "")),
        str(row.get("direction", "")),
        observed_at.isoformat(),
        str(row.get("summary", "")),
    ):
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()[:20]
