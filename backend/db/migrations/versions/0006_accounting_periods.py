"""Add accounting periods registry + period tags on erp_records and invoices.

Formalizes the monthly "accounting period" concept that previously lived only as
a denormalized "YYYY-MM" string on supplier_statements / reconciliation_runs /
reconciliation_results.

New table:
  - accounting_periods: per-org registry of months (powers the month tabs and the
    "Create period" action), with a status for a future close/lock workflow.

New columns (both nullable, indexed):
  - erp_records.period   — stamped from the upload month at ingest time
  - invoices.period      — stamped from the active month at upload time

Backfill (Postgres):
  - erp_records.period   <- to_char(grn_date, 'YYYY-MM')
  - invoices.period      <- to_char(invoice_date, 'YYYY-MM') where invoice_date set
  - accounting_periods   <- every distinct (org_id, period) already present across
                            erp_records, supplier_statements, reconciliation_runs,
                            invoices — so existing months appear as tabs immediately.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- accounting_periods registry ---
    op.create_table(
        "accounting_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("org_id", "period", name="uq_accounting_periods_org_period"),
    )

    # --- period tags on erp_records + invoices ---
    op.add_column("erp_records", sa.Column("period", sa.String(), nullable=True))
    op.create_index("ix_erp_records_period", "erp_records", ["period"])
    op.add_column("invoices", sa.Column("period", sa.String(), nullable=True))
    op.create_index("ix_invoices_period", "invoices", ["period"])

    # --- backfill the period tags from existing dates ---
    op.execute(
        "UPDATE erp_records SET period = to_char(grn_date, 'YYYY-MM') WHERE period IS NULL;"
    )
    op.execute(
        "UPDATE invoices SET period = to_char(invoice_date, 'YYYY-MM') "
        "WHERE period IS NULL AND invoice_date IS NOT NULL;"
    )

    # --- seed the registry from every distinct (org, period) already in the data ---
    op.execute(
        """
        INSERT INTO accounting_periods (id, org_id, period, label, status, created_at, updated_at)
        SELECT gen_random_uuid(),
               src.org_id,
               src.period,
               to_char(to_date(src.period || '-01', 'YYYY-MM-DD'), 'FMMonth YYYY'),
               'open',
               now(),
               now()
        FROM (
            SELECT DISTINCT org_id, period FROM erp_records WHERE period IS NOT NULL
            UNION
            SELECT DISTINCT s.org_id, ss.period
              FROM supplier_statements ss JOIN suppliers s ON s.id = ss.supplier_id
             WHERE ss.period IS NOT NULL
            UNION
            SELECT DISTINCT s.org_id, rr.period
              FROM reconciliation_runs rr JOIN suppliers s ON s.id = rr.supplier_id
             WHERE rr.period IS NOT NULL
            UNION
            SELECT DISTINCT org_id, period FROM invoices WHERE period IS NOT NULL
        ) AS src
        ON CONFLICT (org_id, period) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_period", table_name="invoices")
    op.drop_column("invoices", "period")
    op.drop_index("ix_erp_records_period", table_name="erp_records")
    op.drop_column("erp_records", "period")
    op.drop_table("accounting_periods")
