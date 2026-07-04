"""Escalation lifecycle, validation, tenant scoping, and notification fan-out."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Notification, ReconciliationResult, ReconciliationRun, User

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


def _make_result(db, supplier, period=PERIOD):
    run = ReconciliationRun(
        supplier_id=supplier.id, period=period, status="completed",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    r = ReconciliationResult(
        run_id=run.id, supplier_id=supplier.id, period=period,
        match_type="near_exact", status="pending_review",
        discrepancy_type="price_higher", match_details={"amount": 100.0},
    )
    db.add(r)
    db.commit()
    return r


def _create(client, tenant, **overrides):
    body = {
        "org_id": str(tenant["org"].id),
        "period": PERIOD,
        "title": "Qty mismatch on PO-1001",
        "description": "GRN says 500, statement says 550",
    }
    body.update(overrides)
    return client.post("/api/v1/escalations", json=body)


# --- create ---------------------------------------------------------------


def test_create_free_form(client, tenant):
    login_as(tenant["accountant"])
    resp = _create(client, tenant)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "open"
    assert data["raised_by_name"] == "Accountant User"
    assert data["supplier_id"] is None


def test_create_result_linked_backfills_supplier(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])
    resp = _create(client, tenant, result_id=str(r.id))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["result_id"] == str(r.id)
    assert data["supplier_id"] == str(tenant["supplier"].id)
    assert data["supplier_name"] == tenant["supplier"].name


def test_create_result_period_mismatch_400(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"], period="2026-04")
    login_as(tenant["accountant"])
    resp = _create(client, tenant, result_id=str(r.id))  # escalation says 2026-03
    assert resp.status_code == 400


def test_create_blank_title_400(client, tenant):
    login_as(tenant["accountant"])
    assert _create(client, tenant, title="   ").status_code == 400


# --- lifecycle ------------------------------------------------------------


def test_full_lifecycle(client, db_session, tenant):
    login_as(tenant["accountant"])
    eid = _create(client, tenant).json()["id"]

    login_as(tenant["admin"])
    ack = client.post(f"/api/v1/escalations/{eid}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_by_name"] == "Admin User"

    # Re-acknowledge → 409
    assert client.post(f"/api/v1/escalations/{eid}/acknowledge").status_code == 409

    res = client.post(
        f"/api/v1/escalations/{eid}/resolve",
        json={"resolution_note": "Supplier confirmed corrected statement"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "resolved"
    assert res.json()["resolution_note"] == "Supplier confirmed corrected statement"

    # Re-resolve → 409
    assert (
        client.post(
            f"/api/v1/escalations/{eid}/resolve", json={"resolution_note": "again"}
        ).status_code
        == 409
    )


def test_resolve_from_open_implicitly_acknowledges(client, tenant):
    login_as(tenant["accountant"])
    eid = _create(client, tenant).json()["id"]

    login_as(tenant["admin"])
    res = client.post(
        f"/api/v1/escalations/{eid}/resolve", json={"resolution_note": "done"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "resolved"
    assert data["acknowledged_by_name"] == "Admin User"
    assert data["acknowledged_at"] is not None


def test_resolve_empty_note_400(client, tenant):
    login_as(tenant["accountant"])
    eid = _create(client, tenant).json()["id"]
    login_as(tenant["admin"])
    resp = client.post(
        f"/api/v1/escalations/{eid}/resolve", json={"resolution_note": "  "}
    )
    assert resp.status_code == 400


# --- scoping + listing ----------------------------------------------------


def test_cross_account_gets_404(client, db_session, tenant):
    login_as(tenant["accountant"])
    eid = _create(client, tenant).json()["id"]

    other = seed_tenant(db_session, name="Other Account")
    login_as(other["admin"])
    assert client.get(f"/api/v1/escalations/{eid}").status_code == 404
    assert client.post(f"/api/v1/escalations/{eid}/acknowledge").status_code == 404
    # And the other account's list doesn't include it.
    assert client.get("/api/v1/escalations").json() == []


def test_list_filters(client, db_session, tenant):
    login_as(tenant["accountant"])
    open_id = _create(client, tenant, title="open one").json()["id"]
    _create(client, tenant, title="april", period="2026-04")

    login_as(tenant["admin"])
    client.post(f"/api/v1/escalations/{open_id}/acknowledge")

    all_rows = client.get("/api/v1/escalations").json()
    assert len(all_rows) == 2

    acked = client.get("/api/v1/escalations?status=acknowledged").json()
    assert [e["id"] for e in acked] == [open_id]

    april = client.get(f"/api/v1/escalations?period=2026-04").json()
    assert len(april) == 1 and april[0]["title"] == "april"


# --- notification fan-out ---------------------------------------------------


def test_create_notifies_each_admin_once(client, db_session, tenant):
    # Second admin in the same account; plus an accountant who must NOT be notified.
    admin2 = User(
        account_id=tenant["account"].id, email="admin2@test.test",
        hashed_password="x", full_name="Second Admin", is_active=True,
        is_superuser=False, role="admin",
    )
    db_session.add(admin2)
    db_session.commit()

    login_as(tenant["accountant"])
    resp = _create(client, tenant)
    assert resp.status_code == 201

    rows = db_session.query(Notification).all()
    assert {n.user_id for n in rows} == {tenant["admin"].id, admin2.id}
    assert all(n.type == "escalation_created" for n in rows)
    assert all(n.payload["actor_name"] == "Accountant User" for n in rows)
    assert all(n.payload["escalation_title"] == "Qty mismatch on PO-1001" for n in rows)


def test_ack_and_resolve_notify_raiser_only(client, db_session, tenant):
    login_as(tenant["accountant"])
    eid = _create(client, tenant).json()["id"]
    db_session.query(Notification).delete()
    db_session.commit()

    login_as(tenant["admin"])
    client.post(f"/api/v1/escalations/{eid}/acknowledge")
    client.post(f"/api/v1/escalations/{eid}/resolve", json={"resolution_note": "ok"})

    rows = db_session.query(Notification).order_by(Notification.created_at).all()
    assert len(rows) == 2
    assert all(n.user_id == tenant["accountant"].id for n in rows)
    assert {n.type for n in rows} == {"escalation_acknowledged", "escalation_resolved"}
    resolved = next(n for n in rows if n.type == "escalation_resolved")
    assert resolved.payload["note"] == "ok"


def test_self_resolve_does_not_notify_self(client, db_session, tenant):
    # Admin raises AND resolves their own escalation → no status notification.
    login_as(tenant["admin"])
    eid = _create(client, tenant).json()["id"]
    db_session.query(Notification).delete()
    db_session.commit()

    client.post(f"/api/v1/escalations/{eid}/resolve", json={"resolution_note": "me"})
    assert db_session.query(Notification).count() == 0
