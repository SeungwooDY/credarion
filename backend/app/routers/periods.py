"""API endpoints for accounting periods (monthly containers).

Powers the month-tab switcher and the "Create period" action. Periods are
per-org and keyed by the "YYYY-MM" string used everywhere else for scoping.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccountingPeriod
from app.periods import ensure_period, validate_period

router = APIRouter(prefix="/api/v1/periods", tags=["periods"])


class PeriodCreate(BaseModel):
    org_id: uuid.UUID
    period: str  # "2026-07"


class PeriodResponse(BaseModel):
    id: str
    org_id: str
    period: str
    label: str
    status: str


def _to_response(p: AccountingPeriod) -> PeriodResponse:
    return PeriodResponse(
        id=str(p.id),
        org_id=str(p.org_id),
        period=p.period,
        label=p.label,
        status=p.status,
    )


@router.get("", response_model=list[PeriodResponse])
async def list_periods(
    org_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[PeriodResponse]:
    """List an org's accounting periods, newest month first."""
    periods = (
        db.query(AccountingPeriod)
        .filter(AccountingPeriod.org_id == org_id)
        .order_by(AccountingPeriod.period.desc())
        .all()
    )
    return [_to_response(p) for p in periods]


@router.post("", response_model=PeriodResponse, status_code=201)
async def create_period(
    body: PeriodCreate,
    db: Session = Depends(get_db),
) -> PeriodResponse:
    """Create a new accounting period for an org (idempotent on org+period)."""
    try:
        validate_period(body.period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    period = ensure_period(db, body.org_id, body.period)
    db.commit()
    db.refresh(period)
    return _to_response(period)
