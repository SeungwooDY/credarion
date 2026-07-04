"""Period listing — which accounting months exist for an organization.

No registry table: the period set is DERIVED from stored data (statement
uploads, reconciliation runs, sign-offs), plus the current calendar month so
a brand-new month is selectable before its first upload. Lock state comes
from PeriodSignoff. Newest first.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PeriodSignoff, ReconciliationRun, Supplier, SupplierStatement
from app.periods import current_period, period_label

router = APIRouter(prefix="/api/v1/periods", tags=["periods"])


class PeriodInfo(BaseModel):
    period: str
    label: str
    has_data: bool
    locked: bool


@router.get("", response_model=list[PeriodInfo])
def list_periods(
    org_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
) -> list[PeriodInfo]:
    """Distinct periods for an org, newest first. org_id is auto-scoped by
    the router-level enforce_org_scope dependency (query param)."""
    stmt_periods = {
        p
        for (p,) in db.query(SupplierStatement.period)
        .join(Supplier, SupplierStatement.supplier_id == Supplier.id)
        .filter(Supplier.org_id == org_id)
        .distinct()
        .all()
    }
    run_periods = {
        p
        for (p,) in db.query(ReconciliationRun.period)
        .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
        .filter(Supplier.org_id == org_id)
        .distinct()
        .all()
    }
    signoff_rows = (
        db.query(PeriodSignoff.period, PeriodSignoff.status)
        .filter(PeriodSignoff.org_id == org_id)
        .all()
    )
    signoff_periods = {p for p, _ in signoff_rows}
    locked = {p for p, status in signoff_rows if status == "signed_off"}

    data_periods = stmt_periods | run_periods
    all_periods = data_periods | signoff_periods | {current_period()}

    return [
        PeriodInfo(
            period=p,
            label=period_label(p),
            has_data=p in data_periods,
            locked=p in locked,
        )
        for p in sorted(all_periods, reverse=True)
    ]
