"""Team management endpoints — admins manage their account's users.

Users belong to an ACCOUNT (the tenant); every user sees all of the account's
organizations. Creation always lands in the calling admin's own account, so
there is no cross-tenant surface here. Guards prevent an admin from demoting
or deactivating themselves, and from removing the account's last active admin.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import require_admin
from app.db import get_db
from app.models import User
from app.security import hash_password

router = APIRouter(prefix="/api/v1/users", tags=["users"])

_VALID_ROLES = {"admin", "accountant"}
_MIN_PASSWORD_LEN = 8


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: str = "accountant"


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    is_superuser: bool
    created_at: datetime


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        is_active=u.is_active,
        is_superuser=u.is_superuser,
        created_at=u.created_at,
    )


def _other_active_admins(db: Session, account_id, excluding_id) -> int:
    return (
        db.query(User)
        .filter(
            User.account_id == account_id,
            User.is_active.is_(True),
            User.role == "admin",
            User.id != excluding_id,
        )
        .count()
    )


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> list[UserOut]:
    """All users in the caller's account, newest last."""
    rows = (
        db.query(User)
        .filter(User.account_id == user.account_id)
        .order_by(User.created_at)
        .all()
    )
    return [_to_out(u) for u in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> UserOut:
    """Create a user in the caller's own account with a temporary password."""
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if body.role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail="Role must be admin or accountant")
    if len(body.password) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LEN} characters",
        )
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    new_user = User(
        account_id=user.account_id,
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        is_active=True,
        is_superuser=False,
        role=body.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return _to_out(new_user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> UserOut:
    """Change a user's role or active flag (same account only)."""
    target = db.get(User, user_id)
    # 404 (not 403) for other tenants' users — don't leak existence.
    if target is None or target.account_id != user.account_id:
        raise HTTPException(status_code=404, detail="User not found")

    demoting = body.role is not None and body.role != "admin" and target.role == "admin"
    deactivating = body.is_active is False and target.is_active

    if target.id == user.id and (demoting or deactivating):
        raise HTTPException(
            status_code=400, detail="You cannot demote or deactivate yourself"
        )
    if (demoting or deactivating) and target.role == "admin":
        if _other_active_admins(db, user.account_id, target.id) == 0:
            raise HTTPException(
                status_code=400,
                detail="The account must keep at least one active admin",
            )

    if body.role is not None:
        if body.role not in _VALID_ROLES:
            raise HTTPException(status_code=400, detail="Role must be admin or accountant")
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active

    db.commit()
    db.refresh(target)
    return _to_out(target)
