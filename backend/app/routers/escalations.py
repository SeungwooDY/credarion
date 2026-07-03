"""Escalation endpoints — accountants raise issues, admins review them.

Lifecycle: open → acknowledged → resolved. Resolving an open escalation
implicitly acknowledges it. Escalations are deliberately NOT period-locked:
raising and settling issues about a signed-off month is the workflow the
lock exists to create.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth_deps import authorize_org, get_current_user, require_admin
from app.db import get_db
from app.models import Escalation, Organization, ReconciliationResult, User
from app.notifications import notify_escalation_created, notify_escalation_status

router = APIRouter(prefix="/api/v1/escalations", tags=["escalations"])


class EscalationCreate(BaseModel):
    org_id: uuid.UUID
    period: str
    title: str
    description: str | None = None
    supplier_id: uuid.UUID | None = None
    result_id: uuid.UUID | None = None


class EscalationResolve(BaseModel):
    resolution_note: str


class EscalationOut(BaseModel):
    id: str
    org_id: str
    supplier_id: str | None
    supplier_name: str | None
    result_id: str | None
    period: str
    title: str
    description: str | None
    status: str
    raised_by_name: str | None
    acknowledged_by_name: str | None
    acknowledged_at: datetime | None
    resolved_by_name: str | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime


def _user_name(u: User | None) -> str | None:
    if u is None:
        return None
    return u.full_name or u.email


def _to_out(e: Escalation) -> EscalationOut:
    return EscalationOut(
        id=str(e.id),
        org_id=str(e.org_id),
        supplier_id=str(e.supplier_id) if e.supplier_id else None,
        supplier_name=e.supplier.name if e.supplier else None,
        result_id=str(e.result_id) if e.result_id else None,
        period=e.period,
        title=e.title,
        description=e.description,
        status=e.status,
        raised_by_name=_user_name(e.raised_by),
        acknowledged_by_name=_user_name(e.acknowledged_by),
        acknowledged_at=e.acknowledged_at,
        resolved_by_name=_user_name(e.resolved_by),
        resolved_at=e.resolved_at,
        resolution_note=e.resolution_note,
        created_at=e.created_at,
    )


def _get_scoped(db: Session, escalation_id: uuid.UUID, user: User) -> Escalation:
    e = db.get(Escalation, escalation_id)
    # 404 (not 403) for other tenants' escalations — don't leak existence.
    if e is None or (not user.is_superuser and e.account_id != user.account_id):
        raise HTTPException(status_code=404, detail="Escalation not found")
    return e


@router.post("", response_model=EscalationOut, status_code=201)
def create_escalation(
    body: EscalationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EscalationOut:
    """Raise an escalation (any role). Optionally pinned to a result/supplier."""
    # Body org_id is invisible to the router-level enforce_org_scope.
    authorize_org(db, user, body.org_id)
    org = db.get(Organization, body.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="A title is required")

    supplier_id = body.supplier_id
    if body.result_id is not None:
        result = db.get(ReconciliationResult, body.result_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Result not found")
        if result.period != body.period:
            raise HTTPException(
                status_code=400,
                detail="Result period does not match the escalation period",
            )
        from app.models import Supplier

        supplier = db.get(Supplier, result.supplier_id)
        if supplier is None or supplier.org_id != body.org_id:
            raise HTTPException(
                status_code=400,
                detail="Result does not belong to the given organization",
            )
        supplier_id = result.supplier_id  # backfill from the result

    escalation = Escalation(
        account_id=org.account_id,
        org_id=body.org_id,
        supplier_id=supplier_id,
        result_id=body.result_id,
        period=body.period,
        title=title,
        description=body.description,
        status="open",
        raised_by_id=user.id,
    )
    db.add(escalation)
    db.flush()  # assign id before fan-out references it

    notify_escalation_created(db, escalation, user)
    db.commit()
    db.refresh(escalation)
    return _to_out(escalation)


@router.get("", response_model=list[EscalationOut])
def list_escalations(
    org_id: uuid.UUID | None = Query(None),
    period: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[EscalationOut]:
    """List escalations for the caller's account, newest first."""
    q = db.query(Escalation).options(
        joinedload(Escalation.raised_by),
        joinedload(Escalation.acknowledged_by),
        joinedload(Escalation.resolved_by),
        joinedload(Escalation.supplier),
    )
    if not user.is_superuser:
        q = q.filter(Escalation.account_id == user.account_id)
    if org_id is not None:
        q = q.filter(Escalation.org_id == org_id)
    if period:
        q = q.filter(Escalation.period == period)
    if status:
        q = q.filter(Escalation.status == status)
    return [_to_out(e) for e in q.order_by(Escalation.created_at.desc()).all()]


@router.get("/{escalation_id}", response_model=EscalationOut)
def get_escalation(
    escalation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EscalationOut:
    return _to_out(_get_scoped(db, escalation_id, user))


@router.post("/{escalation_id}/acknowledge", response_model=EscalationOut)
def acknowledge_escalation(
    escalation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> EscalationOut:
    """Mark an escalation as seen by an admin. 409 unless currently open."""
    e = _get_scoped(db, escalation_id, user)
    if e.status != "open":
        raise HTTPException(status_code=409, detail=f"Escalation already {e.status}")

    e.status = "acknowledged"
    e.acknowledged_by_id = user.id
    e.acknowledged_at = datetime.now(timezone.utc)

    notify_escalation_status(db, e, user, "escalation_acknowledged")
    db.commit()
    db.refresh(e)
    return _to_out(e)


@router.post("/{escalation_id}/resolve", response_model=EscalationOut)
def resolve_escalation(
    escalation_id: uuid.UUID,
    body: EscalationResolve,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> EscalationOut:
    """Resolve an escalation with a required note. Implicitly acknowledges."""
    note = body.resolution_note.strip()
    if not note:
        raise HTTPException(status_code=400, detail="A resolution note is required")

    e = _get_scoped(db, escalation_id, user)
    if e.status == "resolved":
        raise HTTPException(status_code=409, detail="Escalation already resolved")

    now = datetime.now(timezone.utc)
    if e.status == "open":  # resolving straight from open implies acknowledgement
        e.acknowledged_by_id = user.id
        e.acknowledged_at = now
    e.status = "resolved"
    e.resolved_by_id = user.id
    e.resolved_at = now
    e.resolution_note = note

    notify_escalation_status(db, e, user, "escalation_resolved")
    db.commit()
    db.refresh(e)
    return _to_out(e)
