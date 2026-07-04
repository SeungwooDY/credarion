"""In-app notification endpoints — list, mark read, mark all read.

Rows are created exclusively by app/notifications.py (fan-out service); this
router only reads and flips read_at for the authenticated user's own rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.db import get_db
from app.models import Notification, User

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    type: str
    payload: dict | None
    escalation_id: str | None
    org_id: str | None
    period: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread_count: int


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(n.id),
        type=n.type,
        payload=n.payload,
        escalation_id=str(n.escalation_id) if n.escalation_id else None,
        org_id=str(n.org_id) if n.org_id else None,
        period=n.period,
        read_at=n.read_at,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationList:
    """The caller's notifications, newest first, plus their unread count."""
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    items = q.order_by(Notification.created_at.desc()).limit(limit).all()

    unread_count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .scalar()
        or 0
    )
    return NotificationList(items=[_to_out(n) for n in items], unread_count=unread_count)


# NOTE: literal route declared before the /{notification_id}/read param route.
@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Mark every unread notification of the caller as read."""
    marked = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .update({Notification.read_at: datetime.now(timezone.utc)})
    )
    db.commit()
    return {"marked": marked}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Mark one of the caller's notifications as read. 404 if not theirs."""
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}
