"""Period sign-off + lock enforcement (423 from mutating endpoints)."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Notification, ReconciliationResult, ReconciliationRun, Supplier

from tests.role_helpers import login_as, make_sqlite_session, seed_tenant

PERIOD = "2026-03"
OTHER_PERIOD = "2026-04"


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


def _make_result(db, supplier, period=PERIOD, status="pending_review"):
    run = ReconciliationRun(
        supplier_id=supplier.id, period=period, status="completed",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    r = ReconciliationResult(
        run_id=run.id,
        supplier_id=supplier.id,
        period=period,
        match_type="near_exact",
        status=status,
        discrepancy_type="price_higher",
        match_details={"amount": 100.0},
    )
    db.add(r)
    db.commit()
    return r


def _sign_off(client, tenant, period=PERIOD):
    login_as(tenant["admin"])
    resp = client.post(
        "/api/v1/signoffs", json={"org_id": str(tenant["org"].id), "period": period}
    )
    assert resp.status_code == 201, resp.text
    return resp


def test_signoff_status_roundtrip(client, tenant):
    login_as(tenant["admin"])
    org_id = str(tenant["org"].id)

    resp = client.get(f"/api/v1/signoffs?org_id={org_id}&period={PERIOD}")
    assert resp.status_code == 200
    assert resp.json() == {
        "locked": False, "status": None, "signed_off_by_name": None,
        "signed_off_at": None, "note": None, "reopened_by_name": None,
        "reopened_at": None, "reopen_note": None,
    }

    _sign_off(client, tenant)
    status = client.get(f"/api/v1/signoffs?org_id={org_id}&period={PERIOD}").json()
    assert status["locked"] is True
    assert status["status"] == "signed_off"
    assert status["signed_off_by_name"] == "Admin User"


def test_double_signoff_409_and_reopen_when_unlocked_409(client, tenant):
    _sign_off(client, tenant)
    resp = client.post(
        "/api/v1/signoffs", json={"org_id": str(tenant["org"].id), "period": PERIOD}
    )
    assert resp.status_code == 409

    body = {"org_id": str(tenant["org"].id), "period": OTHER_PERIOD}
    assert client.post("/api/v1/signoffs/reopen", json=body).status_code == 409


def test_locked_period_blocks_approve_reject_resolve(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    disc = _make_result(db_session, tenant["supplier"], status="unmatched")
    _sign_off(client, tenant)
    login_as(tenant["accountant"])

    assert client.post(
        f"/api/v1/reconciliation/{r.id}/approve", json={}
    ).status_code == 423
    assert client.post(
        f"/api/v1/reconciliation/{r.id}/reject", json={"reason": "nope"}
    ).status_code == 423
    assert client.put(
        f"/api/v1/reconciliation/results/{disc.id}/resolve",
        json={"resolution_note": "fixed"},
    ).status_code == 423


def test_locked_period_blocks_run(client, tenant):
    _sign_off(client, tenant)
    login_as(tenant["accountant"])
    resp = client.post(
        "/api/v1/reconciliation/run",
        json={"supplier_id": str(tenant["supplier"].id), "period": PERIOD},
    )
    assert resp.status_code == 423


def test_bulk_resolve_mixed_periods_rejected_before_any_mutation(
    client, db_session, tenant
):
    locked = _make_result(db_session, tenant["supplier"], period=PERIOD)
    unlocked = _make_result(db_session, tenant["supplier"], period=OTHER_PERIOD)
    _sign_off(client, tenant)  # locks PERIOD only
    login_as(tenant["accountant"])

    resp = client.post(
        "/api/v1/reconciliation/results/bulk-resolve",
        json={
            "result_ids": [str(locked.id), str(unlocked.id)],
            "resolution_note": "batch",
        },
    )
    assert resp.status_code == 423
    # Nothing mutated — including the unlocked-period result.
    db_session.refresh(unlocked)
    assert unlocked.status != "resolved"
    assert unlocked.resolution_note is None


def test_reopen_unblocks(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    _sign_off(client, tenant)
    login_as(tenant["admin"])
    resp = client.post(
        "/api/v1/signoffs/reopen",
        json={"org_id": str(tenant["org"].id), "period": PERIOD},
    )
    assert resp.status_code == 200
    assert resp.json()["locked"] is False

    login_as(tenant["accountant"])
    resp = client.post(f"/api/v1/reconciliation/{r.id}/approve", json={})
    assert resp.status_code == 200, resp.text


def test_other_period_not_locked(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"], period=OTHER_PERIOD)
    _sign_off(client, tenant)  # locks PERIOD, not OTHER_PERIOD
    login_as(tenant["accountant"])
    resp = client.post(f"/api/v1/reconciliation/{r.id}/approve", json={})
    assert resp.status_code == 200, resp.text


def test_signoff_notifies_account_users_except_actor(client, db_session, tenant):
    _sign_off(client, tenant)  # actor = admin
    rows = db_session.query(Notification).all()
    assert len(rows) == 1  # accountant only, not the acting admin
    n = rows[0]
    assert n.user_id == tenant["accountant"].id
    assert n.type == "period_signed_off"
    assert n.payload["actor_name"] == "Admin User"
    assert n.payload["period"] == PERIOD

    login_as(tenant["admin"])
    client.post(
        "/api/v1/signoffs/reopen",
        json={"org_id": str(tenant["org"].id), "period": PERIOD, "note": "redo March"},
    )
    reopen = (
        db_session.query(Notification)
        .filter(Notification.type == "period_reopened")
        .all()
    )
    assert len(reopen) == 1
    assert reopen[0].user_id == tenant["accountant"].id
    assert reopen[0].payload["note"] == "redo March"
