from __future__ import annotations

from collections.abc import Mapping, Sequence


def relevant_source_health(
    source_health: Sequence[Mapping[str, object]],
    *,
    used_sources: set[str],
) -> list[Mapping[str, object]]:
    if not used_sources:
        return list(source_health)
    return [source for source in source_health if str(source.get("source")) in used_sources]


def used_sources(selection_reports: Sequence[Mapping[str, object]]) -> set[str]:
    sources: set[str] = set()
    for report in selection_reports:
        for signal in _report_signals(report):
            provenance = signal.get("provenance")
            if isinstance(provenance, Mapping):
                source = provenance.get("source")
                if isinstance(source, str) and source:
                    sources.add(source)
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
