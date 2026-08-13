"""Period listing + creation — which accounting months exist for an organization.

No registry table: the period set is DERIVED from stored data (statement
uploads, reconciliation runs, sign-offs). New months no longer appear
automatically — they are created explicitly (stored as an "open" PeriodSignoff
row), gated by can_create_period: any past or current month, and future
months through December of next year. A brand-new org with no periods
at all still gets the current month so the app is usable out of the box.
Lock state comes from PeriodSignoff. Newest first.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import authorize_org, get_current_user
from app.db import get_db
from app.models import PeriodSignoff, ReconciliationRun, Supplier, SupplierStatement, User
from app.periods import can_create_period, current_period, period_label, validate_period

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
    all_periods = data_periods | signoff_periods
    # Bootstrap: an org with no periods at all gets the current month so the
    # app is usable before its first upload / explicit creation.
    if not all_periods:
        all_periods = {current_period()}

    return [
        PeriodInfo(
            period=p,
            label=period_label(p),
            has_data=p in data_periods,
            locked=p in locked,
        )
        for p in sorted(all_periods, reverse=True)
    ]


class CreatePeriodRequest(BaseModel):
    org_id: uuid.UUID
    period: str


@router.post("", response_model=PeriodInfo, status_code=201)
def create_period(
    body: CreatePeriodRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PeriodInfo:
    """Explicitly create an accounting month (stored as an "open" sign-off row).

    Allowed for any past or current month, and future months through December
    of next year (see can_create_period). 409 if the period already exists,
    422 if outside the creation window.
    """
    # Body org_id is invisible to the router-level enforce_org_scope.
    authorize_org(db, user, body.org_id)
    try:
        validate_period(body.period)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    existing = (
        db.query(PeriodSignoff)
        .filter(PeriodSignoff.org_id == body.org_id, PeriodSignoff.period == body.period)
        .first()
    )
    has_stmt = (
        db.query(SupplierStatement.id)
        .join(Supplier, SupplierStatement.supplier_id == Supplier.id)
        .filter(Supplier.org_id == body.org_id, SupplierStatement.period == body.period)
        .first()
    )
    has_run = (
        db.query(ReconciliationRun.id)
        .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
        .filter(Supplier.org_id == body.org_id, ReconciliationRun.period == body.period)
        .first()
    )
    if existing is not None or has_stmt is not None or has_run is not None:
        raise HTTPException(
            status_code=409, detail=f"Period {body.period} already exists"
        )

    if not can_create_period(body.period):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Period {body.period} cannot be created — months are only "
                "creatable through December of next year"
            ),
        )

    db.add(PeriodSignoff(org_id=body.org_id, period=body.period, status="open"))
    db.commit()
    return PeriodInfo(
        period=body.period,
        label=period_label(body.period),
        has_data=False,
        locked=False,
    )
