"""Never round supplier numbers: unconstrained NUMERIC for line-level values.

Accountant feedback (2026-07-26): some suppliers quote prices to the 4th
decimal place and beyond (e.g. 0.6575) — these must never be rounded. The
previous fixed scales (prices NUMERIC(12,4), amounts NUMERIC(14,2),
quantities NUMERIC(14,3)) silently rounded anything finer at insert time.

Unconstrained NUMERIC in Postgres stores exact values of any precision, so
ingestion keeps whatever the statement/ERP file says. Widening is metadata-
only in Postgres (no table rewrite).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS: list[tuple[str, str]] = [
    ("erp_records", "quantity"),
    ("erp_records", "po_price"),
    ("erp_records", "unit_price"),
    ("erp_records", "amount"),
    ("statement_line_items", "quantity"),
    ("statement_line_items", "unit_price"),
    ("statement_line_items", "amount"),
    ("reconciliation_results", "quantity_delta"),
    ("reconciliation_results", "price_delta"),
    ("reconciliation_results", "amount_delta"),
]

# Previous fixed scales, for downgrade only (re-applying them rounds).
_OLD_TYPES: dict[str, str] = {
    "quantity": "NUMERIC(14, 3)",
    "po_price": "NUMERIC(12, 4)",
    "unit_price": "NUMERIC(12, 4)",
    "amount": "NUMERIC(14, 2)",
    "quantity_delta": "NUMERIC(14, 3)",
    "price_delta": "NUMERIC(12, 4)",
    "amount_delta": "NUMERIC(14, 2)",
}


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC;")


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {_OLD_TYPES[column]};"
        )
