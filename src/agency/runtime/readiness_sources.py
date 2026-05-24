from __future__ import annotations

from collections.abc import Mapping, Sequence

ALWAYS_RELEVANT_DEGRADED_SOURCES = {"subscription-email-thesis"}
SOURCE_ALIASES = {
    "prices_daily": "daily-market-bars",
    "daily-market-bars": "daily-market-bars",
    "stock_trades": "massive-stock-trades",
    "massive-stock-trades": "massive-stock-trades",
}


def relevant_source_health(
    source_health: Sequence[Mapping[str, object]],
    *,
    used_sources: set[str],
) -> list[Mapping[str, object]]:
    if not used_sources:
        return list(source_health)
    return [
        source
        for source in source_health
        if str(source.get("source")) in used_sources
        or (
            str(source.get("source")) in ALWAYS_RELEVANT_DEGRADED_SOURCES
            and _source_degraded(source)
        )
    ]


def _source_degraded(source: Mapping[str, object]) -> bool:
    status = str(source.get("status") or "").upper()
    freshness = str(source.get("freshness") or "").upper()
    if status in {"STALE", "UNAVAILABLE", "RATE_LIMITED", "ERROR", "FAILED", "BLOCKED"}:
        return True
    return freshness in {"STALE", "UNAVAILABLE"}


def used_sources(selection_reports: Sequence[Mapping[str, object]]) -> set[str]:
    sources: set[str] = set()
    for report in selection_reports:
        for signal in _report_signals(report):
            provenance = signal.get("provenance")
            if isinstance(provenance, Mapping):
                source = provenance.get("source")
                if isinstance(source, str) and source:
                    sources.add(SOURCE_ALIASES.get(source, source))
    return sources


def _report_signals(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    pack = report.get("evidence_pack")
    if not isinstance(pack, Mapping):
        return []
    signals: list[Mapping[str, object]] = []
    for key in ("actionable_signals", "context_signals", "suppressed_signals"):
        values = pack.get(key, [])
        if isinstance(values, list):
            signals.extend(item for item in values if isinstance(item, Mapping))
    return signals
