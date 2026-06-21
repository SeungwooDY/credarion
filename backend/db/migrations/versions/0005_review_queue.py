"""Add human review queue columns to reconciliation_results.

Nothing auto-matches anymore — every reconciliation result is queued for human
review, ranked by a confidence score. This migration adds the columns that drive
that queue and confirm/reject workflow.

New columns on reconciliation_results:
  - confidence_score  INTEGER      DEFAULT 0    (0-100 ranking score)
  - confidence_label  VARCHAR(100)              (e.g. "Exact Match")
  - sort_priority     INTEGER      DEFAULT 99   (1=highest confidence ... 6=no match)
  - discrepancy_note  TEXT                      (inline note for near_exact matches)
  - reviewer_id       VARCHAR                   (who confirmed/rejected)
  - reviewed_at       TIMESTAMP                 (when confirmed/rejected)

Status vocabulary changes (application-enforced; status is a plain String column
with no DB CHECK constraint, so no DDL is required):
  before: matched | discrepancy | resolved
  after:  pending_review | confirmed | rejected | unmatched

This migration is idempotent (ADD COLUMN IF NOT EXISTS) so it is safe to re-run.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE reconciliation_results
          ADD COLUMN IF NOT EXISTS confidence_score INTEGER DEFAULT 0,
          ADD COLUMN IF NOT EXISTS confidence_label VARCHAR(100),
          ADD COLUMN IF NOT EXISTS sort_priority INTEGER DEFAULT 99,
          ADD COLUMN IF NOT EXISTS discrepancy_note TEXT,
          ADD COLUMN IF NOT EXISTS reviewer_id VARCHAR,
          ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
        """
    )
    # Index the queue ordering key so per-supplier review fetches stay fast.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reconciliation_results_sort_priority "
        "ON reconciliation_results (sort_priority);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_reconciliation_results_sort_priority;")
    op.execute(
        """
        ALTER TABLE reconciliation_results
          DROP COLUMN IF EXISTS reviewed_at,
          DROP COLUMN IF EXISTS reviewer_id,
          DROP COLUMN IF EXISTS discrepancy_note,
          DROP COLUMN IF EXISTS sort_priority,
          DROP COLUMN IF EXISTS confidence_label,
          DROP COLUMN IF EXISTS confidence_score;
        """
    )
