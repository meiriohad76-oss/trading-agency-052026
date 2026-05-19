from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from agency.persistence import (
    agent_runs,
    candidate_lifecycle_events,
    data_source_health,
    execution_state_history,
    metadata,
    portfolio_policy,
    portfolio_snapshots,
    prompt_audits,
    risk_decisions,
    risk_snapshots,
    selection_reports,
)


def test_metadata_includes_data_source_health_table() -> None:
    assert metadata.tables["data_source_health"] is data_source_health
    assert metadata.tables["selection_reports"] is selection_reports
    assert metadata.tables["candidate_lifecycle_events"] is candidate_lifecycle_events
    assert metadata.tables["risk_decisions"] is risk_decisions
    assert metadata.tables["agent_runs"] is agent_runs
    assert metadata.tables["prompt_audits"] is prompt_audits
    assert metadata.tables["execution_state_history"] is execution_state_history
    assert metadata.tables["risk_snapshots"] is risk_snapshots
    assert metadata.tables["portfolio_snapshots"] is portfolio_snapshots
    assert metadata.tables["portfolio_policy"] is portfolio_policy


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


def test_runtime_audit_tables_have_key_columns() -> None:
    assert {"run_id", "cycle_id", "agent_name", "status", "payload"}.issubset(
        set(agent_runs.c.keys())
    )
    assert {"prompt_id", "run_id", "prompt_hash", "payload"}.issubset(
        set(prompt_audits.c.keys())
    )
    assert {"state_id", "execution_id", "state", "event_time", "payload"}.issubset(
        set(execution_state_history.c.keys())
    )
    assert {"snapshot_id", "gross_exposure_pct", "risk_level", "payload"}.issubset(
        set(risk_snapshots.c.keys())
    )
    assert agent_runs.primary_key.columns.keys() == ["run_id"]
    assert prompt_audits.primary_key.columns.keys() == ["prompt_id"]
    assert execution_state_history.primary_key.columns.keys() == ["state_id"]
    assert risk_snapshots.primary_key.columns.keys() == ["snapshot_id"]


def test_portfolio_snapshots_table_has_broker_history_columns() -> None:
    columns = set(portfolio_snapshots.c.keys())

    assert {
        "snapshot_id",
        "provider",
        "mode",
        "captured_at",
        "equity",
        "cash",
        "position_count",
        "open_order_count",
        "gross_exposure_pct",
        "payload",
    }.issubset(columns)
    assert portfolio_snapshots.primary_key.columns.keys() == ["snapshot_id"]


def test_runtime_audit_migration_links_to_risk_decision_revision() -> None:
    migration = _load_migration("0006_runtime_audit_tables.py")

    assert migration.revision == "0006_runtime_audit_tables"
    assert migration.down_revision == "0005_risk_decisions"


def test_portfolio_snapshot_migration_links_to_runtime_audit_revision() -> None:
    migration = _load_migration("0007_portfolio_snapshots.py")

    assert migration.revision == "0007_portfolio_snapshots"
    assert migration.down_revision == "0006_runtime_audit_tables"


def test_portfolio_policy_table_has_json_policy_columns() -> None:
    columns = set(portfolio_policy.c.keys())

    assert {"id", "data", "updated_at"}.issubset(columns)
    assert portfolio_policy.primary_key.columns.keys() == ["id"]


def test_portfolio_policy_migration_links_to_portfolio_snapshot_revision() -> None:
    migration = _load_migration("0008_portfolio_policy.py")

    assert migration.revision == "0008_portfolio_policy"
    assert migration.down_revision == "0007_portfolio_snapshots"


def _load_migration(filename: str) -> ModuleType:
    path = Path("migrations") / "versions" / filename
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
