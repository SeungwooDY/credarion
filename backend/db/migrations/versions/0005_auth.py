"""Add authentication: accounts + users, and organizations.account_id.

New tables:
  - accounts: a paying customer (tenant); subscription_status gates login
  - users: login identities (scrypt-hashed passwords) belonging to an account
Altered:
  - organizations: add nullable account_id FK -> accounts

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- accounts ---
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False, server_default="starter"),
        sa.Column(
            "subscription_status", sa.String(), nullable=False, server_default="active"
        ),
        sa.Column("billing_customer_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # --- organizations.account_id ---
    op.add_column(
        "organizations",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_organizations_account_id", "organizations", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_organizations_account_id", table_name="organizations")
    op.drop_column("organizations", "account_id")
    op.drop_table("users")
    op.drop_table("accounts")
