"""Create risk decisions table.

Revision ID: 0005_risk_decisions
Revises: 0004_candidate_lifecycle_events
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_risk_decisions"
down_revision: str | None = "0004_candidate_lifecycle_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_decisions",
        sa.Column("cycle_id", sa.String(length=120), primary_key=True),
        sa.Column("ticker", sa.String(length=16), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
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
    op.create_index("ix_risk_decisions_ticker", "risk_decisions", ["ticker"])
    op.create_index("ix_risk_decisions_decision", "risk_decisions", ["decision"])


def downgrade() -> None:
    op.drop_index("ix_risk_decisions_decision", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_ticker", table_name="risk_decisions")
    op.drop_table("risk_decisions")
