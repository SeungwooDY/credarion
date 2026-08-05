"""Mark-as-Discrepancy on reconciliation results.

Mismatch-page workflow (2026-08-05): a reviewer can mark a row as a genuine
discrepancy and must state why. The reason is shown on the row and flows into
the spreadsheet CSV export's Notes column. Orthogonal to resolve — a marked
row stays open until resolved.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reconciliation_results",
        sa.Column("marked_discrepancy_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("marked_discrepancy_by", sa.String(), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("marked_discrepancy_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reconciliation_results", "marked_discrepancy_at")
    op.drop_column("reconciliation_results", "marked_discrepancy_by")
    op.drop_column("reconciliation_results", "marked_discrepancy_reason")
