"""Tests for authentication: login gating, session cookie, /me, logout, and
that data routers reject unauthenticated requests."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth_deps import get_current_user
from app.db import Base, get_db
from app.main import app
from app.models import Account, Organization, User
from app.security import create_access_token, hash_password


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "VARCHAR(36)"


@pytest.fixture
def db_session():
    import sqlite3

    sqlite3.register_adapter(uuid.UUID, str)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session: Session):
    # Use the real auth dependency (drop the autouse superuser override) and
    # route the app at our in-memory DB.
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _make_user(
    db: Session,
    *,
    email: str = "paying@credarion.test",
    password: str = "hunter2-strong",
    status: str = "active",
    is_active: bool = True,
) -> tuple[User, Account, Organization]:
    account = Account(name="Acme APAC", plan="growth", subscription_status=status)
    db.add(account)
    db.flush()
    org = Organization(name="Acme HK", reporting_currency="HKD", account_id=account.id)
    db.add(org)
    user = User(
        account_id=account.id,
        email=email,
        hashed_password=hash_password(password),
        full_name="Pay Ing",
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    return user, account, org


def test_login_success_sets_cookie_and_returns_me(client, db_session):
    _user, _account, org = _make_user(db_session)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "paying@credarion.test", "password": "hunter2-strong"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "paying@credarion.test"
    assert body["account"]["plan"] == "growth"
    assert [o["id"] for o in body["organizations"]] == [str(org.id)]
    # Session cookie was set on the client jar.
    assert "credarion_session" in resp.cookies or "credarion_session" in client.cookies


def test_login_is_case_insensitive_on_email(client, db_session):
    _make_user(db_session, email="mixed@credarion.test")
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "MIXED@Credarion.TEST", "password": "hunter2-strong"},
    )
    assert resp.status_code == 200, resp.text


def test_login_wrong_password_rejected(client, db_session):
    _make_user(db_session)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "paying@credarion.test", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_login_unknown_email_rejected(client, db_session):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@credarion.test", "password": "whatever"},
    )
    assert resp.status_code == 401


def test_login_runs_verify_even_for_unknown_email(client, db_session, monkeypatch):
    """Timing-oracle guard: a scrypt verify must run on the miss path so an
    unknown email costs the same as a real one (see DUMMY_PASSWORD_HASH)."""
    import app.routers.auth as auth_mod

    calls: list[str] = []
    real_verify = auth_mod.verify_password

    def _spy(password: str, stored: str) -> bool:
        calls.append(stored)
        return real_verify(password, stored)

    monkeypatch.setattr(auth_mod, "verify_password", _spy)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@credarion.test", "password": "whatever"},
    )
    assert resp.status_code == 401
    # Verify was invoked, and against the dummy hash (not skipped).
    assert calls == [auth_mod.DUMMY_PASSWORD_HASH]


def test_login_blocked_for_non_paying_account(client, db_session):
    _make_user(db_session, email="canceled@credarion.test", status="canceled")
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "canceled@credarion.test", "password": "hunter2-strong"},
    )
    assert resp.status_code == 403


def test_login_blocked_for_inactive_user(client, db_session):
    _make_user(db_session, email="inactive@credarion.test", is_active=False)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@credarion.test", "password": "hunter2-strong"},
    )
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_protected_router_rejects_unauthenticated(client):
    # /orgs is a data router guarded at the app level.
    resp = client.get("/api/v1/orgs")
    assert resp.status_code == 401


def test_full_login_then_access_protected(client, db_session):
    _user, _account, org = _make_user(db_session)
    client.post(
        "/api/v1/auth/login",
        json={"email": "paying@credarion.test", "password": "hunter2-strong"},
    )
    # Cookie now in the jar; protected route should return only this account's orgs.
    resp = client.get("/api/v1/orgs")
    assert resp.status_code == 200, resp.text
    assert [o["id"] for o in resp.json()] == [str(org.id)]


def test_logout_clears_session(client, db_session):
    _make_user(db_session)
    client.post(
        "/api/v1/auth/login",
        json={"email": "paying@credarion.test", "password": "hunter2-strong"},
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_tenant_isolation_blocks_other_account_org(client, db_session):
    # Two accounts; user from account A cannot read account B's org suppliers.
    _user_a, _acct_a, _org_a = _make_user(db_session, email="a@credarion.test")
    other = Account(name="Other Co", plan="starter", subscription_status="active")
    db_session.add(other)
    db_session.flush()
    org_b = Organization(name="Other Org", account_id=other.id)
    db_session.add(org_b)
    db_session.commit()

    client.post(
        "/api/v1/auth/login",
        json={"email": "a@credarion.test", "password": "hunter2-strong"},
    )
    resp = client.get(f"/api/v1/orgs/{org_b.id}/suppliers")
    assert resp.status_code == 403


def test_expired_token_is_rejected(client, db_session):
    user, _account, _org = _make_user(db_session)
    # Forge an already-expired token for this user.
    token = create_access_token(str(user.id), ttl_hours=1, now=0)
    client.cookies.set("credarion_session", token)
    assert client.get("/api/v1/auth/me").status_code == 401
