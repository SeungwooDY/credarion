"""Notification fan-out rules — the ONLY place Notification rows are created.

Each helper adds rows to the session WITHOUT committing; the calling route
handler's single db.commit() keeps the domain change and its notifications
atomic. Payloads carry i18n tokens (actor_name, period, org_name, ...) so the
frontend renders localized text from type + payload — no English baked in.

Actors are never notified of their own actions.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Escalation, Notification, Organization, User


def _actor_name(actor: User) -> str:
    return actor.full_name or actor.email


def _admins_of_account(db: Session, account_id, exclude_user_id) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.account_id == account_id,
            User.is_active.is_(True),
            User.role == "admin",
            User.id != exclude_user_id,
        )
        .all()
    )


def _users_of_account(db: Session, account_id, exclude_user_id) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.account_id == account_id,
            User.is_active.is_(True),
            User.id != exclude_user_id,
        )
        .all()
    )


def notify_escalation_created(db: Session, escalation: Escalation, actor: User) -> None:
    """Escalation raised → every active admin in the account (except the actor)."""
    payload = {
        "actor_name": _actor_name(actor),
        "period": escalation.period,
        "escalation_title": escalation.title,
    }
    for admin in _admins_of_account(db, escalation.account_id, actor.id):
        db.add(
            Notification(
                user_id=admin.id,
                type="escalation_created",
                payload=payload,
                escalation_id=escalation.id,
                org_id=escalation.org_id,
                period=escalation.period,
            )
        )


def notify_escalation_status(
    db: Session, escalation: Escalation, actor: User, event: str
) -> None:
    """Acknowledge/resolve → the accountant who raised the escalation.

    ``event`` is "escalation_acknowledged" or "escalation_resolved". Skipped
    when the raiser is the actor themselves or no longer exists.
    """
    if escalation.raised_by_id is None or escalation.raised_by_id == actor.id:
        return
    payload = {
        "actor_name": _actor_name(actor),
        "period": escalation.period,
        "escalation_title": escalation.title,
    }
    if event == "escalation_resolved" and escalation.resolution_note:
        payload["note"] = escalation.resolution_note
    db.add(
        Notification(
            user_id=escalation.raised_by_id,
            type=event,
            payload=payload,
            escalation_id=escalation.id,
            org_id=escalation.org_id,
            period=escalation.period,
        )
    )


def notify_period_event(
    db: Session,
    org: Organization,
    period: str,
    actor: User,
    event: str,
    note: str | None,
) -> None:
    """Sign-off/reopen → every active user in the account (except the actor).

    ``event`` is "period_signed_off" or "period_reopened".
    """
    payload: dict[str, str] = {
        "actor_name": _actor_name(actor),
        "period": period,
        "org_name": org.name,
    }
    if note:
        payload["note"] = note
    for recipient in _users_of_account(db, org.account_id, actor.id):
        db.add(
            Notification(
                user_id=recipient.id,
                type=event,
                payload=payload,
                org_id=org.id,
                period=period,
            )
        )
