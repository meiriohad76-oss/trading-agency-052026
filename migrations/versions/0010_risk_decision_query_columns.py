"""Add query columns for risk decisions.

Revision ID: 0010_risk_decision_query_columns
Revises: 0009_runtime_generated_at_indexes
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_risk_decision_query_columns"
down_revision: str | None = "0009_runtime_generated_at_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("risk_decisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "final_action",
                sa.String(length=40),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
        batch_op.add_column(
            sa.Column(
                "final_conviction",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch_op.create_index(
            "ix_risk_decisions_final_action",
            ["final_action"],
        )


def downgrade() -> None:
    with op.batch_alter_table("risk_decisions") as batch_op:
        batch_op.drop_index("ix_risk_decisions_final_action")
        batch_op.drop_column("final_conviction")
        batch_op.drop_column("final_action")
