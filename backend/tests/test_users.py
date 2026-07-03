"""Team management: list/create/update users, admin gating, guardrails."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.security import verify_password

from tests.role_helpers import login_as, make_sqlite_session, seed_tenant


@pytest.fixture
def db_session():
    session = make_sqlite_session()
    yield session
    session.close()


@pytest.fixture
def tenant(db_session):
    return seed_tenant(db_session)


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_body(**overrides):
    body = {
        "email": "new.user@test.test",
        "password": "temp-password-1",
        "full_name": "New User",
        "role": "accountant",
    }
    body.update(overrides)
    return body


# --- gating -----------------------------------------------------------------


def test_accountant_cannot_manage_team(client, tenant):
    login_as(tenant["accountant"])
    assert client.get("/api/v1/users").status_code == 403
    assert client.post("/api/v1/users", json=_create_body()).status_code == 403
    assert (
        client.patch(
            f"/api/v1/users/{tenant['admin'].id}", json={"role": "accountant"}
        ).status_code
        == 403
    )


# --- list -------------------------------------------------------------------


def test_list_scoped_to_own_account(client, db_session, tenant):
    other = seed_tenant(db_session, name="Other Account")
    login_as(tenant["admin"])
    emails = {u["email"] for u in client.get("/api/v1/users").json()}
    assert tenant["admin"].email in emails
    assert tenant["accountant"].email in emails
    assert other["admin"].email not in emails


# --- create -----------------------------------------------------------------


def test_create_lands_in_admins_account(client, db_session, tenant):
    login_as(tenant["admin"])
    resp = client.post("/api/v1/users", json=_create_body())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["role"] == "accountant"
    assert data["is_active"] is True

    from app.models import User

    created = db_session.query(User).filter(User.email == "new.user@test.test").one()
    assert created.account_id == tenant["admin"].account_id
    assert verify_password("temp-password-1", created.hashed_password)


def test_create_validations(client, tenant):
    login_as(tenant["admin"])
    # Duplicate email → 409
    assert client.post("/api/v1/users", json=_create_body()).status_code == 201
    assert client.post("/api/v1/users", json=_create_body()).status_code == 409
    # Bad role / short password / bad email → 400
    assert (
        client.post("/api/v1/users", json=_create_body(email="x@y.z", role="owner")).status_code
        == 400
    )
    assert (
        client.post("/api/v1/users", json=_create_body(email="x@y.z", password="short")).status_code
        == 400
    )
    assert client.post("/api/v1/users", json=_create_body(email="not-an-email")).status_code == 400


# --- update -----------------------------------------------------------------


def test_promote_and_demote(client, db_session, tenant):
    login_as(tenant["admin"])
    uid = str(tenant["accountant"].id)

    resp = client.patch(f"/api/v1/users/{uid}", json={"role": "admin"})
    assert resp.status_code == 200 and resp.json()["role"] == "admin"

    # Now two admins exist, so demoting the second one back is allowed.
    resp = client.patch(f"/api/v1/users/{uid}", json={"role": "accountant"})
    assert resp.status_code == 200 and resp.json()["role"] == "accountant"


def test_cannot_demote_or_deactivate_self(client, tenant):
    login_as(tenant["admin"])
    uid = str(tenant["admin"].id)
    assert client.patch(f"/api/v1/users/{uid}", json={"role": "accountant"}).status_code == 400
    assert client.patch(f"/api/v1/users/{uid}", json={"is_active": False}).status_code == 400


def test_last_admin_guard(client, db_session, tenant):
    # Promote the accountant, then have THEM try to demote the original admin
    # after the original admin was already demoted... simpler: second admin
    # demotes the first, then nobody can demote the remaining one.
    login_as(tenant["admin"])
    client.patch(f"/api/v1/users/{tenant['accountant'].id}", json={"role": "admin"})

    login_as(tenant["accountant"])  # now an admin
    resp = client.patch(f"/api/v1/users/{tenant['admin'].id}", json={"role": "accountant"})
    assert resp.status_code == 200

    # tenant["accountant"] is now the only active admin — deactivating or
    # demoting them (even by themselves) is blocked.
    resp = client.patch(f"/api/v1/users/{tenant['accountant'].id}", json={"is_active": False})
    assert resp.status_code == 400


def test_cross_account_user_404(client, db_session, tenant):
    other = seed_tenant(db_session, name="Other Account")
    login_as(tenant["admin"])
    resp = client.patch(f"/api/v1/users/{other['accountant'].id}", json={"role": "admin"})
    assert resp.status_code == 404


# --- change password ----------------------------------------------------------


def test_change_password(client, db_session, tenant):
    from app.security import hash_password

    user = tenant["accountant"]
    user.hashed_password = hash_password("old-password-1")
    db_session.commit()

    login_as(user)
    # Wrong current password → 401
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong", "new_password": "new-password-1"},
    )
    assert resp.status_code == 401
    # Too-short new password → 400
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-1", "new_password": "short"},
    )
    assert resp.status_code == 400
    # Happy path
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-1", "new_password": "new-password-1"},
    )
    assert resp.status_code == 200
    db_session.refresh(user)
    assert verify_password("new-password-1", user.hashed_password)
