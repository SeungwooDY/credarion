"""Unresolve endpoint (mismatch page): revert a resolution with confirmation.

DELETE /results/{id}/resolve clears the resolution fields and reopens the
row — "unmatched" rows go back to unmatched, everything else to
pending_review. The note is gone for good (the UI warns before confirming).
"""
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


def _make_result(db, supplier, match_type="near_exact", status="pending_review",
                 discrepancy_type="price_higher", period=PERIOD):
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
        match_type=match_type,
        status=status,
        discrepancy_type=discrepancy_type,
        match_details={"amount": 100.0},
    )
    db.add(r)
    db.commit()
    return r


def _resolve(client, r) -> None:
    resp = client.put(
        f"/api/v1/reconciliation/results/{r.id}/resolve",
        json={"resolution_note": "checked with supplier"},
    )
    assert resp.status_code == 200, resp.text


def test_unresolve_reopens_reviewed_row(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])
    _resolve(client, r)

    resp = client.delete(f"/api/v1/reconciliation/results/{r.id}/resolve")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending_review"
    assert body["resolution_note"] is None
    assert body["resolved_by"] is None
    assert body["resolved_at"] is None


def test_unresolve_restores_unmatched_status(client, db_session, tenant):
    r = _make_result(
        db_session, tenant["supplier"],
        match_type="unmatched", status="unmatched",
        discrepancy_type="missing_from_erp",
    )
    login_as(tenant["accountant"])
    _resolve(client, r)

    resp = client.delete(f"/api/v1/reconciliation/results/{r.id}/resolve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "unmatched"


def test_unresolve_requires_resolved_row(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])

    resp = client.delete(f"/api/v1/reconciliation/results/{r.id}/resolve")
    assert resp.status_code == 400


def test_locked_period_blocks_unresolve(client, db_session, tenant):
    r = _make_result(db_session, tenant["supplier"])
    login_as(tenant["accountant"])
    _resolve(client, r)

    login_as(tenant["admin"])
    resp = client.post(
        "/api/v1/signoffs", json={"org_id": str(tenant["org"].id), "period": PERIOD}
    )
    assert resp.status_code == 201, resp.text
    login_as(tenant["accountant"])

    assert client.delete(
        f"/api/v1/reconciliation/results/{r.id}/resolve"
    ).status_code == 423
