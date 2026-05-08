from __future__ import annotations

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy import Column as Col

metadata = MetaData()

data_source_health = Table(
    "data_source_health",
    metadata,
    Col("source", String(length=120), primary_key=True),
    Col("source_tier", String(length=40), nullable=False),
    Col("status", String(length=40), nullable=False),
    Col("checked_at", DateTime(timezone=True), nullable=False),
    Col("freshness", String(length=40), nullable=False),
    Col("last_success_at", DateTime(timezone=True)),
    Col("observed_lag_seconds", Float),
    Col("error_count", Integer, nullable=False, server_default="0"),
    Col("reliability_score", Float, nullable=False),
    Col("rate_limit_reset_at", DateTime(timezone=True)),
    Col("notes", JSON, nullable=False),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Col("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Col("last_error", Text),
)

selection_reports = Table(
    "selection_reports",
    metadata,
    Col("cycle_id", String(length=120), primary_key=True),
    Col("ticker", String(length=16), primary_key=True),
    Col("as_of", DateTime(timezone=True), primary_key=True),
    Col("generated_at", DateTime(timezone=True), nullable=False),
    Col("final_action", String(length=40), nullable=False),
    Col("final_conviction", Float, nullable=False),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Col("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

risk_decisions = Table(
    "risk_decisions",
    metadata,
    Col("cycle_id", String(length=120), primary_key=True),
    Col("ticker", String(length=16), primary_key=True),
    Col("as_of", DateTime(timezone=True), primary_key=True),
    Col("generated_at", DateTime(timezone=True), nullable=False),
    Col("decision", String(length=40), nullable=False),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Col("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

agent_runs = Table(
    "agent_runs",
    metadata,
    Col("run_id", String(length=120), primary_key=True),
    Col("cycle_id", String(length=120), nullable=False),
    Col("agent_name", String(length=120), nullable=False),
    Col("status", String(length=40), nullable=False),
    Col("trigger", String(length=40), nullable=False),
    Col("started_at", DateTime(timezone=True), nullable=False),
    Col("finished_at", DateTime(timezone=True)),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Col("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

prompt_audits = Table(
    "prompt_audits",
    metadata,
    Col("prompt_id", String(length=120), primary_key=True),
    Col("run_id", String(length=120)),
    Col("cycle_id", String(length=120), nullable=False),
    Col("agent_name", String(length=120), nullable=False),
    Col("model", String(length=120), nullable=False),
    Col("prompt_class", String(length=120), nullable=False),
    Col("prompt_hash", String(length=128), nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False),
    Col("redaction_status", String(length=40), nullable=False),
    Col("payload", JSON, nullable=False),
    Col("inserted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

execution_state_history = Table(
    "execution_state_history",
    metadata,
    Col("state_id", String(length=120), primary_key=True),
    Col("cycle_id", String(length=120), nullable=False),
    Col("ticker", String(length=16)),
    Col("execution_id", String(length=120), nullable=False),
    Col("state", String(length=40), nullable=False),
    Col("event_time", DateTime(timezone=True), nullable=False),
    Col("reason", Text),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

risk_snapshots = Table(
    "risk_snapshots",
    metadata,
    Col("snapshot_id", String(length=120), primary_key=True),
    Col("cycle_id", String(length=120), nullable=False),
    Col("ticker", String(length=16)),
    Col("as_of", DateTime(timezone=True), nullable=False),
    Col("generated_at", DateTime(timezone=True), nullable=False),
    Col("gross_exposure_pct", Float, nullable=False),
    Col("risk_level", String(length=40), nullable=False),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

candidate_lifecycle_events = Table(
    "candidate_lifecycle_events",
    metadata,
    Col("event_id", String(length=64), primary_key=True),
    Col("cycle_id", String(length=120), nullable=False),
    Col("ticker", String(length=16), nullable=False),
    Col("event_type", String(length=60), nullable=False),
    Col("event_time", DateTime(timezone=True), nullable=False),
    Col("status", String(length=60), nullable=False),
    Col("reason", Text),
    Col("payload", JSON, nullable=False),
    Col("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
