"""Initial empty schema baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06
"""

from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema objects are created in T02."""


def downgrade() -> None:
    """No schema objects are removed in T02."""
