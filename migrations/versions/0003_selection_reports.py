"""Create selection reports table.

Revision ID: 0003_selection_reports
Revises: 0002_data_source_health
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_selection_reports"
down_revision: str | None = "0002_data_source_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "selection_reports",
        sa.Column("cycle_id", sa.String(length=120), primary_key=True),
        sa.Column("ticker", sa.String(length=16), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_action", sa.String(length=40), nullable=False),
        sa.Column("final_conviction", sa.Float, nullable=False),
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
    op.create_check_constraint(
        "ck_selection_reports_final_conviction",
        "selection_reports",
        "final_conviction >= 0 AND final_conviction <= 1",
    )
    op.create_index("ix_selection_reports_ticker", "selection_reports", ["ticker"])
    op.create_index("ix_selection_reports_final_action", "selection_reports", ["final_action"])


def downgrade() -> None:
    op.drop_index("ix_selection_reports_final_action", table_name="selection_reports")
    op.drop_index("ix_selection_reports_ticker", table_name="selection_reports")
    op.drop_table("selection_reports")
