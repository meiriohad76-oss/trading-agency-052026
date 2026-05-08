"""Create runtime audit tables.

Revision ID: 0006_runtime_audit_tables
Revises: 0005_risk_decisions
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_runtime_audit_tables"
down_revision: str | None = "0005_risk_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=120), primary_key=True),
        sa.Column("cycle_id", sa.String(length=120), nullable=False),
        sa.Column("agent_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_runs_cycle_id", "agent_runs", ["cycle_id"])
    op.create_index("ix_agent_runs_agent_status", "agent_runs", ["agent_name", "status"])

    op.create_table(
        "prompt_audits",
        sa.Column("prompt_id", sa.String(length=120), primary_key=True),
        sa.Column("run_id", sa.String(length=120)),
        sa.Column("cycle_id", sa.String(length=120), nullable=False),
        sa.Column("agent_name", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_class", sa.String(length=120), nullable=False),
        sa.Column("prompt_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redaction_status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_prompt_audits_cycle_id", "prompt_audits", ["cycle_id"])
    op.create_index("ix_prompt_audits_run_id", "prompt_audits", ["run_id"])

    op.create_table(
        "execution_state_history",
        sa.Column("state_id", sa.String(length=120), primary_key=True),
        sa.Column("cycle_id", sa.String(length=120), nullable=False),
        sa.Column("ticker", sa.String(length=16)),
        sa.Column("execution_id", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_execution_state_history_cycle_ticker",
        "execution_state_history",
        ["cycle_id", "ticker"],
    )
    op.create_index("ix_execution_state_history_state", "execution_state_history", ["state"])

    op.create_table(
        "risk_snapshots",
        sa.Column("snapshot_id", sa.String(length=120), primary_key=True),
        sa.Column("cycle_id", sa.String(length=120), nullable=False),
        sa.Column("ticker", sa.String(length=16)),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gross_exposure_pct", sa.Float, nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_risk_snapshots_cycle_ticker", "risk_snapshots", ["cycle_id", "ticker"])
    op.create_index("ix_risk_snapshots_risk_level", "risk_snapshots", ["risk_level"])


def downgrade() -> None:
    op.drop_index("ix_risk_snapshots_risk_level", table_name="risk_snapshots")
    op.drop_index("ix_risk_snapshots_cycle_ticker", table_name="risk_snapshots")
    op.drop_table("risk_snapshots")
    op.drop_index("ix_execution_state_history_state", table_name="execution_state_history")
    op.drop_index(
        "ix_execution_state_history_cycle_ticker",
        table_name="execution_state_history",
    )
    op.drop_table("execution_state_history")
    op.drop_index("ix_prompt_audits_run_id", table_name="prompt_audits")
    op.drop_index("ix_prompt_audits_cycle_id", table_name="prompt_audits")
    op.drop_table("prompt_audits")
    op.drop_index("ix_agent_runs_agent_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_cycle_id", table_name="agent_runs")
    op.drop_table("agent_runs")
