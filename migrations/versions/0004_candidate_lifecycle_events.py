"""Create candidate lifecycle events table.

Revision ID: 0004_candidate_lifecycle_events
Revises: 0003_selection_reports
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_candidate_lifecycle_events"
down_revision: str | None = "0003_selection_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_lifecycle_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("cycle_id", sa.String(length=120), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
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
        "ix_candidate_lifecycle_events_cycle_ticker",
        "candidate_lifecycle_events",
        ["cycle_id", "ticker"],
    )
    op.create_index(
        "ix_candidate_lifecycle_events_type_time",
        "candidate_lifecycle_events",
        ["event_type", "event_time"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_lifecycle_events_type_time",
        table_name="candidate_lifecycle_events",
    )
    op.drop_index(
        "ix_candidate_lifecycle_events_cycle_ticker",
        table_name="candidate_lifecycle_events",
    )
    op.drop_table("candidate_lifecycle_events")
