from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from agency.persistence import (
    candidate_lifecycle_events,
    data_source_health,
    metadata,
    risk_decisions,
    selection_reports,
)


def test_metadata_includes_data_source_health_table() -> None:
    assert metadata.tables["data_source_health"] is data_source_health
    assert metadata.tables["selection_reports"] is selection_reports
    assert metadata.tables["candidate_lifecycle_events"] is candidate_lifecycle_events
    assert metadata.tables["risk_decisions"] is risk_decisions


def test_data_source_health_table_has_runtime_status_columns() -> None:
    columns = set(data_source_health.c.keys())

    assert {
        "source",
        "source_tier",
        "status",
        "checked_at",
        "freshness",
        "reliability_score",
        "payload",
        "updated_at",
    }.issubset(columns)
    assert data_source_health.primary_key.columns.keys() == ["source"]


def test_data_source_health_migration_links_to_initial_revision() -> None:
    migration = _load_migration("0002_data_source_health.py")

    assert migration.revision == "0002_data_source_health"
    assert migration.down_revision == "0001_initial"


def test_selection_reports_table_has_audit_key_columns() -> None:
    columns = set(selection_reports.c.keys())

    assert {"cycle_id", "ticker", "as_of", "final_action", "payload"}.issubset(columns)
    assert selection_reports.primary_key.columns.keys() == ["cycle_id", "ticker", "as_of"]


def test_selection_reports_migration_links_to_source_health_revision() -> None:
    migration = _load_migration("0003_selection_reports.py")

    assert migration.revision == "0003_selection_reports"
    assert migration.down_revision == "0002_data_source_health"


def test_candidate_lifecycle_events_table_has_audit_columns() -> None:
    columns = set(candidate_lifecycle_events.c.keys())

    assert {
        "event_id",
        "cycle_id",
        "ticker",
        "event_type",
        "event_time",
        "status",
        "payload",
    }.issubset(columns)
    assert candidate_lifecycle_events.primary_key.columns.keys() == ["event_id"]


def test_candidate_lifecycle_events_migration_links_to_selection_report_revision() -> None:
    migration = _load_migration("0004_candidate_lifecycle_events.py")

    assert migration.revision == "0004_candidate_lifecycle_events"
    assert migration.down_revision == "0003_selection_reports"


def test_risk_decisions_table_has_audit_key_columns() -> None:
    columns = set(risk_decisions.c.keys())

    assert {"cycle_id", "ticker", "as_of", "decision", "payload"}.issubset(columns)
    assert risk_decisions.primary_key.columns.keys() == ["cycle_id", "ticker", "as_of"]


def test_risk_decisions_migration_links_to_lifecycle_revision() -> None:
    migration = _load_migration("0005_risk_decisions.py")

    assert migration.revision == "0005_risk_decisions"
    assert migration.down_revision == "0004_candidate_lifecycle_events"


def _load_migration(filename: str) -> ModuleType:
    path = Path("migrations") / "versions" / filename
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
