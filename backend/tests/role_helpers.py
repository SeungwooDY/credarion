"""Shared fixtures/helpers for role-aware router tests.

The autouse conftest override authenticates every request as a detached
superuser, which bypasses org scoping. Role tests instead need PERSISTED users
(so account-scoped queries match seeded rows) and per-test control over who is
logged in. ``login_as`` replaces the ``get_current_user`` override — and since
``require_admin`` composes over ``get_current_user``, one override gates both.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.main import app
from app.models import Account, Organization, Supplier, User


def make_sqlite_session():
    """In-memory SQLite session with the pg->sqlite type shims installed."""
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "JSON"

    @compiles(PG_UUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "VARCHAR(36)"

    import sqlite3

    sqlite3.register_adapter(uuid.UUID, lambda u: str(u))
    sqlite3.register_converter("UUID", lambda b: uuid.UUID(b.decode()))

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_tenant(db: Session, *, name: str = "Test Account") -> dict:
    """Persist an account + org + supplier + admin/accountant users.

    Returns a dict with keys: account, org, supplier, admin, accountant.
    """
    account = Account(name=name, plan="growth", subscription_status="active")
    db.add(account)
    db.flush()

    org = Organization(name=f"{name} Org", reporting_currency="RMB", account_id=account.id)
    db.add(org)
    db.flush()

    supplier = Supplier(org_id=org.id, vendor_code="SDD201", name="奥雄电子有限公司")
    db.add(supplier)

    admin = User(
        account_id=account.id,
        email=f"admin@{name.lower().replace(' ', '-')}.test",
        hashed_password="x",
        full_name="Admin User",
        is_active=True,
        is_superuser=False,
        role="admin",
    )
    accountant = User(
        account_id=account.id,
        email=f"accountant@{name.lower().replace(' ', '-')}.test",
        hashed_password="x",
        full_name="Accountant User",
        is_active=True,
        is_superuser=False,
        role="accountant",
    )
    db.add_all([admin, accountant])
    db.commit()
    return {
        "account": account,
        "org": org,
        "supplier": supplier,
        "admin": admin,
        "accountant": accountant,
    }


def login_as(user: User) -> None:
    """Authenticate all subsequent client requests as the given persisted user."""
    app.dependency_overrides[get_current_user] = lambda: user
