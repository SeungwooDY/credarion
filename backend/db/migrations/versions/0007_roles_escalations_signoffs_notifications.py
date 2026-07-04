"""Roles, escalations, period sign-offs, and in-app notifications.

Adds the admin/accountant permission split and the collaboration workflow
around month-end close:

  - users.role VARCHAR DEFAULT 'accountant'   (admin | accountant; existing
    superusers are promoted to admin)
  - escalations        — issues accountants raise for admin review, optionally
    pinned to a supplier and/or reconciliation result
  - period_signoffs    — one current-state row per (org, period); while
    status='signed_off' the period is locked (mutations rejected with 423)
  - notifications      — per-user in-app notifications; payload JSONB carries
    i18n tokens so the client renders localized text

This migration is idempotent (IF NOT EXISTS everywhere) so it is safe to re-run.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users.role -------------------------------------------------------
    op.execute(
        """
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS role VARCHAR NOT NULL DEFAULT 'accountant';
        """
    )
    # Existing platform/seed superusers keep full capability under the new tier.
    op.execute("UPDATE users SET role = 'admin' WHERE is_superuser;")

    # --- escalations ------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS escalations (
            id UUID PRIMARY KEY,
            account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL,
            result_id UUID REFERENCES reconciliation_results(id) ON DELETE SET NULL,
            period VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            description TEXT,
            status VARCHAR NOT NULL DEFAULT 'open',
            raised_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            acknowledged_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            acknowledged_at TIMESTAMPTZ,
            resolved_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            resolved_at TIMESTAMPTZ,
            resolution_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_escalations_account_status "
        "ON escalations (account_id, status);"
    )

    # --- period_signoffs --------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS period_signoffs (
            id UUID PRIMARY KEY,
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            period VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'signed_off',
            signed_off_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            signed_off_at TIMESTAMPTZ,
            note TEXT,
            reopened_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            reopened_at TIMESTAMPTZ,
            reopen_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_period_signoffs_org_period UNIQUE (org_id, period)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_period_signoffs_org_period "
        "ON period_signoffs (org_id, period);"
    )

    # --- notifications ----------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type VARCHAR NOT NULL,
            payload JSONB,
            escalation_id UUID REFERENCES escalations(id) ON DELETE SET NULL,
            org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            period VARCHAR,
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_created "
        "ON notifications (user_id, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_user_created;")
    op.execute("DROP TABLE IF EXISTS notifications;")
    op.execute("DROP INDEX IF EXISTS ix_period_signoffs_org_period;")
    op.execute("DROP TABLE IF EXISTS period_signoffs;")
    op.execute("DROP INDEX IF EXISTS ix_escalations_account_status;")
    op.execute("DROP TABLE IF EXISTS escalations;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role;")
