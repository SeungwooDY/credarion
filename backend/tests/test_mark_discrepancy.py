"""Mark-as-Discrepancy endpoints (mismatch page): mark, unmark, lock, export field."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import ReconciliationResult, ReconciliationRun

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


def _make_result(db, supplier, discrepancy_type="price_higher", period=PERIOD):
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
        status="pending_review",
        discrepancy_type=discrepancy_type,
        match_details={"amount": 100.0},
    )
    db.add(r)
    db.commit()
    return r


def test_mark_happy_path(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])

    resp = client.put(
        f"/api/v1/reconciliation/results/{r.id}/mark-discrepancy",
        json={"reason": "Supplier billed at old price"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["marked_discrepancy_reason"] == "Supplier billed at old price"
    assert body["marked_discrepancy_by"] == tenant["accountant"].email
    assert body["marked_discrepancy_at"] is not None
    # Marking is orthogonal to resolution — the row stays open.
    assert body["status"] == "pending_review"


def test_mark_blank_reason_rejected(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])

    resp = client.put(
        f"/api/v1/reconciliation/results/{r.id}/mark-discrepancy",
        json={"reason": "   "},
    )
    assert resp.status_code == 422
    db_session.refresh(r)
    assert r.marked_discrepancy_reason is None


def test_mark_non_discrepancy_rejected(client, db_session, tenant):
    clean = _make_result(db_session, tenant["supplier"], discrepancy_type=None)
    login_as(tenant["accountant"])

    resp = client.put(
        f"/api/v1/reconciliation/results/{clean.id}/mark-discrepancy",
        json={"reason": "should not work"},
    )
    assert resp.status_code == 400


def test_remark_overwrites_reason(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])
    url = f"/api/v1/reconciliation/results/{r.id}/mark-discrepancy"

    assert client.put(url, json={"reason": "first"}).status_code == 200
    resp = client.put(url, json={"reason": "second"})
    assert resp.status_code == 200
    assert resp.json()["marked_discrepancy_reason"] == "second"


def test_unmark_clears_fields(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])
    url = f"/api/v1/reconciliation/results/{r.id}/mark-discrepancy"

    assert client.put(url, json={"reason": "oops"}).status_code == 200
    resp = client.delete(url)
    assert resp.status_code == 200
    body = resp.json()
    assert body["marked_discrepancy_reason"] is None
    assert body["marked_discrepancy_by"] is None
    assert body["marked_discrepancy_at"] is None


def test_locked_period_blocks_mark_and_unmark(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["admin"])
    resp = client.post(
        "/api/v1/signoffs", json={"org_id": str(tenant["org"].id), "period": PERIOD}
    )
    assert resp.status_code == 201, resp.text
    login_as(tenant["accountant"])

    url = f"/api/v1/reconciliation/results/{r.id}/mark-discrepancy"
    assert client.put(url, json={"reason": "late"}).status_code == 423
    assert client.delete(url).status_code == 423


def test_mismatches_endpoint_exposes_mark(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])
    assert client.put(
        f"/api/v1/reconciliation/results/{r.id}/mark-discrepancy",
        json={"reason": "confirmed with supplier"},
    ).status_code == 200

    resp = client.get(
        f"/api/v1/reconciliation/mismatches?org_id={tenant['org'].id}&period={PERIOD}"
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()[0]["items"]
    marked = next(i for i in items if i["id"] == str(r.id))
    assert marked["marked_discrepancy_reason"] == "confirmed with supplier"
    assert marked["marked_discrepancy_at"] is not None
