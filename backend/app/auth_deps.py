"""FastAPI auth dependencies and tenant-isolation helpers."""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Organization, Supplier, User
from app.security import decode_access_token

_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the logged-in user from the session cookie.

    Raises 401 if the cookie is missing/invalid/expired, the user no longer
    exists or is deactivated, or the user's account is not a paying customer.
    """
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise _UNAUTH

    payload = decode_access_token(token)
    if not payload:
        raise _UNAUTH

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise _UNAUTH

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTH

    # Billing gate: only paying customers may use the app.
    if user.account is None or not user.account.is_paying:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your subscription is not active. Please contact support.",
        )

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """403 unless the user is an account admin.

    Platform superusers pass too — they must be able to unstick pilot
    accounts, and this keeps the test-suite superuser override working for
    non-role-specific tests.
    """
    if user.role != "admin" and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


def authorize_org(
    db: Session, user: User, org_id: uuid.UUID | str | None
) -> None:
    """Ensure ``user`` may access the given organization.

    Superusers may access any org. Everyone else may only touch orgs owned by
    their own account. A no-op when ``org_id`` is None.
    """
    if org_id is None or user.is_superuser:
        return

    try:
        oid = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org = db.get(Organization, oid)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.account_id != user.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )


def authorize_supplier(
    db: Session, user: User, supplier_id: uuid.UUID | str | None
) -> None:
    """Ensure ``user`` may access the org that owns the given supplier."""
    if supplier_id is None or user.is_superuser:
        return
    try:
        sid = (
            supplier_id
            if isinstance(supplier_id, uuid.UUID)
            else uuid.UUID(str(supplier_id))
        )
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")

    supplier = db.get(Supplier, sid)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    authorize_org(db, user, supplier.org_id)


def accessible_org_ids(db: Session, user: User) -> set[uuid.UUID] | None:
    """Org IDs owned by the user's account.

    Returns ``None`` for superusers, meaning "unrestricted" — callers should
    skip filtering entirely in that case rather than treat it as an empty set.
    """
    if user.is_superuser:
        return None
    rows = (
        db.query(Organization.id)
        .filter(Organization.account_id == user.account_id)
        .all()
    )
    return {row[0] for row in rows}


def accessible_supplier_ids(db: Session, user: User) -> set[uuid.UUID] | None:
    """Supplier IDs the user's account may access (via its orgs).

    Returns ``None`` for superusers, meaning "unrestricted" (see
    :func:`accessible_org_ids`).
    """
    if user.is_superuser:
        return None
    rows = (
        db.query(Supplier.id)
        .join(Organization, Supplier.org_id == Organization.id)
        .filter(Organization.account_id == user.account_id)
        .all()
    )
    return {row[0] for row in rows}


def enforce_org_scope(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Router-level dependency: authenticate, then auto-check any ``org_id``
    present in the path or query string against the user's account.

    Endpoints that receive ``org_id`` in a form field or request body must call
    :func:`authorize_org` explicitly, since those aren't visible here.
    """
    org_id = request.path_params.get("org_id") or request.query_params.get("org_id")
    authorize_org(db, user, org_id)
    return user
