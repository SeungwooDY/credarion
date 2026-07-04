"""Month-end sign-off endpoints.

An admin signs off an org+period, which locks it (see app/period_lock.py);
reopening unlocks. One current-state row per (org, period).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import authorize_org, get_current_user, require_admin
from app.db import get_db
from app.models import Organization, PeriodSignoff, User
from app.notifications import notify_period_event

router = APIRouter(prefix="/api/v1/signoffs", tags=["signoffs"])


class SignoffRequest(BaseModel):
    org_id: uuid.UUID
    period: str
    note: str | None = None


class SignoffStatus(BaseModel):
    locked: bool
    status: str | None = None
    signed_off_by_name: str | None = None
    signed_off_at: datetime | None = None
    note: str | None = None
    reopened_by_name: str | None = None
    reopened_at: datetime | None = None
    reopen_note: str | None = None


def _status_payload(signoff: PeriodSignoff | None) -> SignoffStatus:
    if signoff is None:
        return SignoffStatus(locked=False)
    return SignoffStatus(
        locked=signoff.status == "signed_off",
        status=signoff.status,
        signed_off_by_name=(
            signoff.signed_off_by.full_name or signoff.signed_off_by.email
            if signoff.signed_off_by
            else None
        ),
        signed_off_at=signoff.signed_off_at,
        note=signoff.note,
        reopened_by_name=(
            signoff.reopened_by.full_name or signoff.reopened_by.email
            if signoff.reopened_by
            else None
        ),
        reopened_at=signoff.reopened_at,
        reopen_note=signoff.reopen_note,
    )


def _get_signoff(db: Session, org_id: uuid.UUID, period: str) -> PeriodSignoff | None:
    return (
        db.query(PeriodSignoff)
        .filter(PeriodSignoff.org_id == org_id, PeriodSignoff.period == period)
        .first()
    )


@router.get("", response_model=SignoffStatus)
def get_signoff_status(
    org_id: uuid.UUID = Query(...),
    period: str = Query(...),
    db: Session = Depends(get_db),
) -> SignoffStatus:
    """Current sign-off/lock state for an org+period (org_id auto-scoped)."""
    return _status_payload(_get_signoff(db, org_id, period))


@router.post("", response_model=SignoffStatus, status_code=201)
def sign_off_period(
    body: SignoffRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SignoffStatus:
    """Sign off (lock) a period. Admin only. 409 if already signed off."""
    # Body org_id is invisible to the router-level enforce_org_scope.
    authorize_org(db, user, body.org_id)
    org = db.get(Organization, body.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    signoff = _get_signoff(db, body.org_id, body.period)
    if signoff is not None and signoff.status == "signed_off":
        raise HTTPException(
            status_code=409, detail=f"Period {body.period} is already signed off"
        )

    now = datetime.now(timezone.utc)
    if signoff is None:
        signoff = PeriodSignoff(org_id=body.org_id, period=body.period)
        db.add(signoff)
    signoff.status = "signed_off"
    signoff.signed_off_by_id = user.id
    signoff.signed_off_at = now
    signoff.note = body.note
    signoff.reopened_by_id = None
    signoff.reopened_at = None
    signoff.reopen_note = None

    notify_period_event(db, org, body.period, user, "period_signed_off", body.note)
    db.commit()
    db.refresh(signoff)
    return _status_payload(signoff)


@router.post("/reopen", response_model=SignoffStatus)
def reopen_period(
    body: SignoffRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SignoffStatus:
    """Reopen (unlock) a signed-off period. Admin only. 409 if not locked."""
    authorize_org(db, user, body.org_id)
    org = db.get(Organization, body.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    signoff = _get_signoff(db, body.org_id, body.period)
    if signoff is None or signoff.status != "signed_off":
        raise HTTPException(
            status_code=409, detail=f"Period {body.period} is not signed off"
        )

    signoff.status = "reopened"
    signoff.reopened_by_id = user.id
    signoff.reopened_at = datetime.now(timezone.utc)
    signoff.reopen_note = body.note

    notify_period_event(db, org, body.period, user, "period_reopened", body.note)
    db.commit()
    db.refresh(signoff)
    return _status_payload(signoff)
