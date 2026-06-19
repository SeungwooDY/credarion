"""Authentication endpoints: login, logout, and current-user lookup."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models import Organization, User
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class OrgSummary(BaseModel):
    id: str
    name: str
    reporting_currency: str


class AccountSummary(BaseModel):
    id: str
    name: str
    plan: str
    subscription_status: str


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    is_superuser: bool
    account: AccountSummary
    organizations: list[OrgSummary]


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        max_age=settings.auth_token_ttl_hours * 3600,
        path="/",
    )


def _me_payload(user: User, db: Session) -> MeResponse:
    if user.is_superuser:
        orgs = db.query(Organization).all()
    else:
        orgs = (
            db.query(Organization)
            .filter(Organization.account_id == user.account_id)
            .all()
        )
    return MeResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_superuser=user.is_superuser,
        account=AccountSummary(
            id=str(user.account.id),
            name=user.account.name,
            plan=user.account.plan,
            subscription_status=user.account.subscription_status,
        ),
        organizations=[
            OrgSummary(id=str(o.id), name=o.name, reporting_currency=o.reporting_currency)
            for o in orgs
        ],
    )


@router.post("/login", response_model=MeResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> MeResponse:
    """Authenticate a paying customer and set the session cookie.

    Returns 401 for unknown email / wrong password / inactive user, and 403 if
    the user's account is not a paying subscriber. The error message is kept
    generic for credential failures to avoid leaking which emails exist.
    """
    email = body.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.account is None or not user.account.is_paying:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your subscription is not active. Please contact support.",
        )

    token = create_access_token(str(user.id))
    _set_session_cookie(response, token)
    return _me_payload(user, db)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    """Clear the session cookie."""
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    """Return the current user along with their account and accessible orgs."""
    return _me_payload(user, db)
