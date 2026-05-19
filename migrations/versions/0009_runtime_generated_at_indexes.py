"""Add generated_at indexes for runtime dashboard reads.

Revision ID: 0009_runtime_generated_at_indexes
Revises: 0008_portfolio_policy
Create Date: 2026-05-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_runtime_generated_at_indexes"
down_revision: str | None = "0008_portfolio_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_selection_reports_generated_at",
        "selection_reports",
        ["generated_at"],
    )
    op.create_index(
        "ix_selection_reports_ticker_generated_at",
        "selection_reports",
        ["ticker", "generated_at"],
    )
    op.create_index(
        "ix_risk_decisions_generated_at",
        "risk_decisions",
        ["generated_at"],
    )
    op.create_index(
        "ix_risk_decisions_ticker_generated_at",
        "risk_decisions",
        ["ticker", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_decisions_ticker_generated_at",
        table_name="risk_decisions",
    )
    op.drop_index("ix_risk_decisions_generated_at", table_name="risk_decisions")
    op.drop_index(
        "ix_selection_reports_ticker_generated_at",
        table_name="selection_reports",
    )
    op.drop_index("ix_selection_reports_generated_at", table_name="selection_reports")
