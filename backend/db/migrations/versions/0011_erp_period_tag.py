"""Period tag on ERP records — pairing scope by upload, not grn_date.

Monthly SGWERP exports routinely contain rows dated in neighbouring months
("overflowed dates" — e.g. the pilot's March export carries 135 February
receipts). Scoping reconciliation by the grn_date calendar window made those
rows invisible to their month's run, producing phantom "not in ERP"
discrepancies (PCX201, 2026-08-12). Each upload is now stamped with the
accounting month it was uploaded FOR, and pairing scopes by that tag; dates
are only used to combine rows and break ties.

Backfill: existing rows get the dominant grn_date month of their
(org, source_file) upload batch, so stragglers stay with their batch.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: the shared dev DB already carries this column + index from
    # the abandoned period-ingestion branch (applied outside this chain);
    # prod does not. Guard both so the migration works everywhere.
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("erp_records")]
    if "period" not in cols:
        op.add_column("erp_records", sa.Column("period", sa.String(), nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_erp_records_period ON erp_records (period)"
    )

    # Backfill: dominant grn_date month per (org, source_file) batch.
    op.execute(
        """
        WITH dominant AS (
            SELECT org_id, source_file, month AS period
            FROM (
                SELECT org_id, source_file,
                       to_char(grn_date, 'YYYY-MM') AS month,
                       ROW_NUMBER() OVER (
                           PARTITION BY org_id, source_file
                           ORDER BY count(*) DESC, to_char(grn_date, 'YYYY-MM') DESC
                       ) AS rn
                FROM erp_records
                GROUP BY org_id, source_file, to_char(grn_date, 'YYYY-MM')
            ) ranked
            WHERE rn = 1
        )
        UPDATE erp_records e
        SET period = d.period
        FROM dominant d
        WHERE e.org_id = d.org_id AND e.source_file = d.source_file
        """
    )


def downgrade() -> None:
    op.drop_index("ix_erp_records_period", table_name="erp_records")
    op.drop_column("erp_records", "period")
