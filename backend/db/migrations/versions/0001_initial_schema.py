"""Initial schema — supplier reconciliation wedge.

Implements the Technical Build Handoff (April 2026) schema plus approved deltas:
  - erp_records.quantity and statement_line_items.quantity are NUMERIC(14,3)
  - erp_records and statement_line_items carry a raw_row JSONB column
  - No delivery_notes table

Revision ID: 0001
Revises:
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False, server_default="RMB"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vendor_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("is_cross_border", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "vendor_code", name="uq_suppliers_org_vendor_code"),
    )
    op.create_index("ix_suppliers_org_id", "suppliers", ["org_id"])

    op.create_table(
        "erp_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("po_number", sa.String(), nullable=False),
        sa.Column("material_number", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("po_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("vat_rate", sa.Integer(), nullable=True),
        sa.Column("grn_number", sa.String(), nullable=False),
        sa.Column("grn_date", sa.DateTime(timezone=False), nullable=False),
        sa.Column("delivery_order", sa.String(), nullable=True),
        sa.Column("delivery_note", sa.String(), nullable=True),
        sa.Column("source_file", sa.String(), nullable=False),
        sa.Column("raw_row", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_erp_records_po_number", "erp_records", ["po_number"])
    op.create_index("ix_erp_records_material_number", "erp_records", ["material_number"])
    op.create_index("ix_erp_records_delivery_note", "erp_records", ["delivery_note"])
    op.create_index(
        "ix_erp_records_supplier_po_pn",
        "erp_records",
        ["supplier_id", "po_number", "material_number"],
    )

    op.create_table(
        "supplier_statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("file_url", sa.String(), nullable=False),
        sa.Column(
            "upload_date",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_supplier_statements_supplier_period",
        "supplier_statements",
        ["supplier_id", "period"],
    )

    op.create_table(
        "statement_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "statement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("po_number", sa.String(), nullable=True),
        sa.Column("material_number", sa.String(), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("delivery_note_ref", sa.String(), nullable=True),
        sa.Column("raw_row", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_statement_line_items_po_number", "statement_line_items", ["po_number"])
    op.create_index(
        "ix_statement_line_items_material_number",
        "statement_line_items",
        ["material_number"],
    )
    op.create_index(
        "ix_statement_line_items_statement_id",
        "statement_line_items",
        ["statement_id"],
    )

    op.create_table(
        "reconciliation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column(
            "erp_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("erp_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "statement_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("statement_line_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("match_type", sa.String(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(14, 3), nullable=True),
        sa.Column("price_delta", sa.Numeric(12, 4), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_reconciliation_results_supplier_period",
        "reconciliation_results",
        ["supplier_id", "period"],
    )


def downgrade() -> None:
    op.drop_table("reconciliation_results")
    op.drop_table("statement_line_items")
    op.drop_table("supplier_statements")
    op.drop_table("erp_records")
    op.drop_table("suppliers")
    op.drop_table("organizations")
