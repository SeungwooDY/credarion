"""Supplier aliases — learned alternate names for a supplier.

A supplier prints its own name on statement letterheads differently from how
the buyer's ERP records it (e.g. full-width brackets, branch qualifiers, trade
names). With only a single canonical name per supplier, the statement→supplier
auto-match silently mis-bound files (2026-09-29: 沃福（宁波）… landed on 广东诚博…
because the full-width brackets truncated the detected name to a generic tail).

This table lets the system learn name→supplier mappings: when a user binds a
statement to a supplier whose detected name isn't already an exact match, the
detected name is saved here so future uploads resolve automatically.
normalized_alias is unique per org so one spelling can't map to two suppliers.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplier_aliases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias_name", sa.String(), nullable=False),
        sa.Column("normalized_alias", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "org_id", "normalized_alias", name="uq_supplier_aliases_org_normalized"
        ),
    )
    op.create_index(
        "ix_supplier_aliases_normalized_alias",
        "supplier_aliases",
        ["normalized_alias"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supplier_aliases_normalized_alias", table_name="supplier_aliases"
    )
    op.drop_table("supplier_aliases")
