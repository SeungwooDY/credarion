"""Period-lock enforcement for month-end sign-off.

When an admin signs off an org+period (see routers/signoffs.py), that period is
LOCKED: every endpoint that mutates period-scoped data must call one of the
helpers below first and will fail with **423 Locked** until an admin reopens.

Locked call sites: statement upload, reconciliation run, resolve/bulk-resolve,
approve/reject. Deliberately EXEMPT:
  - Escalations — raising/handling issues about a locked period is precisely
    the workflow sign-off creates.
  - Sign-off/reopen themselves.
  - ERP/GRN upload (v1 gap): GRN rows carry a per-row grn_date and the upload
    has no single period parameter, so there is nothing cheap to check. A v2
    could reject rows whose grn_date falls in a locked month.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import PeriodSignoff, ReconciliationResult, Supplier


def ensure_period_unlocked(db: Session, org_id: uuid.UUID, period: str) -> None:
    """Raise 423 Locked when the org+period has been signed off."""
    signoff = (
        db.query(PeriodSignoff)
        .filter(
            PeriodSignoff.org_id == org_id,
            PeriodSignoff.period == period,
            PeriodSignoff.status == "signed_off",
        )
        .first()
    )
    if signoff is not None:
        raise HTTPException(
            status_code=423,
            detail={
                "message": f"Period {period} has been signed off and is locked",
                "org_id": str(org_id),
                "period": period,
            },
        )


def ensure_supplier_period_unlocked(
    db: Session, supplier_id: uuid.UUID, period: str
) -> None:
    """Resolve the supplier's org, then check the lock."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        return  # let the endpoint's own 404 handling deal with it
    ensure_period_unlocked(db, supplier.org_id, period)


def ensure_result_period_unlocked(db: Session, result: ReconciliationResult) -> None:
    """Check the lock for the org+period a reconciliation result belongs to."""
    ensure_supplier_period_unlocked(db, result.supplier_id, result.period)
