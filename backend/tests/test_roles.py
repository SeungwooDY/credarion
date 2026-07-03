"""Role gating: admins/superusers pass require_admin, accountants get 403."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app

from tests.role_helpers import login_as, make_sqlite_session, seed_tenant

PERIOD = "2026-03"


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


def _signoff_body(tenant) -> dict:
    return {"org_id": str(tenant["org"].id), "period": PERIOD}


def test_accountant_cannot_sign_off(client, tenant):
    login_as(tenant["accountant"])
    resp = client.post("/api/v1/signoffs", json=_signoff_body(tenant))
    assert resp.status_code == 403
    assert "Admin role required" in resp.text


def test_accountant_cannot_reopen(client, tenant):
    login_as(tenant["accountant"])
    resp = client.post("/api/v1/signoffs/reopen", json=_signoff_body(tenant))
    assert resp.status_code == 403


def test_admin_can_sign_off_and_reopen(client, tenant):
    login_as(tenant["admin"])
    resp = client.post("/api/v1/signoffs", json=_signoff_body(tenant))
    assert resp.status_code == 201, resp.text
    assert resp.json()["locked"] is True

    resp = client.post("/api/v1/signoffs/reopen", json=_signoff_body(tenant))
    assert resp.status_code == 200, resp.text
    assert resp.json()["locked"] is False


def test_accountant_cannot_acknowledge_or_resolve_escalation(client, tenant):
    login_as(tenant["accountant"])
    created = client.post(
        "/api/v1/escalations",
        json={
            "org_id": str(tenant["org"].id),
            "period": PERIOD,
            "title": "Price variance looks wrong",
        },
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    assert client.post(f"/api/v1/escalations/{eid}/acknowledge").status_code == 403
    assert (
        client.post(
            f"/api/v1/escalations/{eid}/resolve",
            json={"resolution_note": "n/a"},
        ).status_code
        == 403
    )


def test_superuser_passes_admin_gate(client, db_session, tenant):
    # The conftest autouse override authenticates as a detached superuser;
    # superusers bypass org scoping and imply admin capability.
    resp = client.post("/api/v1/signoffs", json=_signoff_body(tenant))
    assert resp.status_code == 201, resp.text


def test_role_in_me_payload(client, tenant):
    login_as(tenant["accountant"])
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "accountant"

    login_as(tenant["admin"])
    assert client.get("/api/v1/auth/me").json()["role"] == "admin"
