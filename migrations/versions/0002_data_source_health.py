"""Create data source health table.

Revision ID: 0002_data_source_health
Revises: 0001_initial
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_data_source_health"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_source_health",
        sa.Column("source", sa.String(length=120), primary_key=True),
        sa.Column("source_tier", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness", sa.String(length=40), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("observed_lag_seconds", sa.Float),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reliability_score", sa.Float, nullable=False),
        sa.Column("rate_limit_reset_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.JSON, nullable=False),
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
        sa.Column("last_error", sa.Text),
    )
    op.create_check_constraint(
        "ck_data_source_health_reliability_score",
        "data_source_health",
        "reliability_score >= 0 AND reliability_score <= 1",
    )
    op.create_check_constraint(
        "ck_data_source_health_error_count",
        "data_source_health",
        "error_count >= 0",
    )


def downgrade() -> None:
    op.drop_table("data_source_health")
