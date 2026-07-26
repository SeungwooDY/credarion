"""Statement annotation support + configurable date tolerance.

Accountant-review features (2026-07):
  - supplier_statements.original_filename  VARCHAR — the uploaded file's name,
    used when serving the annotated export.
  - statement_line_items.source_row        INTEGER — 1-based Excel row number of
    the line in the ORIGINAL uploaded file, so the annotated export can write
    results/notes back onto the exact rows the supplier sent.
  - reconciliation_config.date_tolerance_days INTEGER DEFAULT 3 — ERP grn_date
    vs statement delivery_date window. Date gaps beyond the window never block
    a match; they surface as a "match with note" in the review queue.

Idempotent (ADD COLUMN IF NOT EXISTS) so it is safe to re-run.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE supplier_statements "
        "ADD COLUMN IF NOT EXISTS original_filename VARCHAR;"
    )
    op.execute(
        "ALTER TABLE statement_line_items "
        "ADD COLUMN IF NOT EXISTS source_row INTEGER;"
    )
    op.execute(
        "ALTER TABLE reconciliation_config "
        "ADD COLUMN IF NOT EXISTS date_tolerance_days INTEGER NOT NULL DEFAULT 3;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE reconciliation_config DROP COLUMN IF EXISTS date_tolerance_days;"
    )
    op.execute(
        "ALTER TABLE statement_line_items DROP COLUMN IF EXISTS source_row;"
    )
    op.execute(
        "ALTER TABLE supplier_statements DROP COLUMN IF EXISTS original_filename;"
    )
