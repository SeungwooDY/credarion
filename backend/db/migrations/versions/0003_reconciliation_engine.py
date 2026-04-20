"""Add reconciliation engine tables and extend reconciliation_results.

New tables:
  - reconciliation_runs: tracks each reconciliation execution
  - reconciliation_config: per-org tolerance settings

Altered table:
  - reconciliation_results: add run_id, amount_delta, discrepancy_type,
    confidence, resolved_by, resolved_at, match_details

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- reconciliation_runs ---
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("total_erp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_statement", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discrepancy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_match_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_reconciliation_runs_supplier_period",
        "reconciliation_runs",
        ["supplier_id", "period"],
    )

    # --- reconciliation_config ---
    op.create_table(
        "reconciliation_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "qty_tolerance_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0.50",
        ),
        sa.Column(
            "price_tolerance_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0.50",
        ),
        sa.Column(
            "auto_resolve_exact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "ai_layer_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "ai_max_tokens_per_run",
            sa.Integer(),
            nullable=False,
            server_default="10000",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", name="uq_reconciliation_config_org_id"),
    )

    # --- Alter reconciliation_results ---
    op.add_column(
        "reconciliation_results",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("amount_delta", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("discrepancy_type", sa.String(), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("resolved_by", sa.String(), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reconciliation_results",
        sa.Column(
            "match_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_reconciliation_results_run_id",
        "reconciliation_results",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_results_run_id", table_name="reconciliation_results")
    op.drop_column("reconciliation_results", "match_details")
    op.drop_column("reconciliation_results", "resolved_at")
    op.drop_column("reconciliation_results", "resolved_by")
    op.drop_column("reconciliation_results", "confidence")
    op.drop_column("reconciliation_results", "discrepancy_type")
    op.drop_column("reconciliation_results", "amount_delta")
    op.drop_column("reconciliation_results", "run_id")
    op.drop_table("reconciliation_config")
    op.drop_table("reconciliation_runs")
