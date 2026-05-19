"""Create portfolio snapshots.

Revision ID: 0007_portfolio_snapshots
Revises: 0006_runtime_audit_tables
Create Date: 2026-05-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_portfolio_snapshots"
down_revision: str | None = "0006_runtime_audit_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("snapshot_id", sa.String(length=120), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_status", sa.String(length=40), nullable=False),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("cash", sa.Float, nullable=False),
        sa.Column("buying_power", sa.Float, nullable=False),
        sa.Column("portfolio_value", sa.Float, nullable=False),
        sa.Column("position_count", sa.Integer, nullable=False),
        sa.Column("open_order_count", sa.Integer, nullable=False),
        sa.Column("gross_exposure_pct", sa.Float, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_portfolio_snapshots_captured_at",
        "portfolio_snapshots",
        ["captured_at"],
    )
    op.create_index(
        "ix_portfolio_snapshots_provider_mode",
        "portfolio_snapshots",
        ["provider", "mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_snapshots_provider_mode", table_name="portfolio_snapshots")
    op.drop_index("ix_portfolio_snapshots_captured_at", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
