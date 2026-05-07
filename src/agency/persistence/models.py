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
