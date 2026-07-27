"""POST /reconciliation/results/bulk-approve — section-level Confirm All."""
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


def _make_results(db, supplier, n=3, status="pending_review", period=PERIOD):
    run = ReconciliationRun(
        supplier_id=supplier.id, period=period, status="completed",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    out = []
    for _ in range(n):
        r = ReconciliationResult(
            run_id=run.id, supplier_id=supplier.id, period=period,
            match_type="exact", status=status, match_details={"amount": 100.0},
        )
        db.add(r)
        out.append(r)
    db.commit()
    return out


def test_bulk_approve_confirms_pending(client, db_session, tenant):
    results = _make_results(db_session, tenant["supplier"], n=3)
    login_as(tenant["accountant"])

    resp = client.post(
        "/api/v1/reconciliation/results/bulk-approve",
        json={"result_ids": [str(r.id) for r in results]},
    )
    assert resp.status_code == 200, resp.text
    assert all(item["status"] == "confirmed" for item in resp.json())

    for r in results:
        db_session.refresh(r)
        assert r.status == "confirmed"
        assert r.reviewer_id == tenant["accountant"].email
        assert r.reviewed_at is not None


def test_bulk_approve_skips_already_reviewed(client, db_session, tenant):
    """Already-reviewed rows are skipped, not a batch-wide 409."""
    pending = _make_results(db_session, tenant["supplier"], n=1)[0]
    rejected = _make_results(db_session, tenant["supplier"], n=1, status="rejected")[0]
    login_as(tenant["accountant"])

    resp = client.post(
        "/api/v1/reconciliation/results/bulk-approve",
        json={"result_ids": [str(pending.id), str(rejected.id)]},
    )
    assert resp.status_code == 200
    statuses = {item["id"]: item["status"] for item in resp.json()}
    assert statuses[str(pending.id)] == "confirmed"
    assert statuses[str(rejected.id)] == "rejected"  # untouched

    db_session.refresh(rejected)
    assert rejected.status == "rejected"


def test_bulk_approve_cross_tenant_404(client, db_session, tenant):
    other = seed_tenant(db_session, name="Other Account")
    theirs = _make_results(db_session, other["supplier"], n=1)[0]
    mine = _make_results(db_session, tenant["supplier"], n=1)[0]
    login_as(tenant["accountant"])

    resp = client.post(
        "/api/v1/reconciliation/results/bulk-approve",
        json={"result_ids": [str(mine.id), str(theirs.id)]},
    )
    assert resp.status_code == 404

    # Nothing mutated on either side.
    db_session.refresh(mine)
    db_session.refresh(theirs)
    assert mine.status == "pending_review"
    assert theirs.status == "pending_review"


def test_bulk_approve_locked_period_423(client, db_session, tenant):
    results = _make_results(db_session, tenant["supplier"], n=2)
    login_as(tenant["admin"])
    assert client.post(
        "/api/v1/signoffs",
        json={"org_id": str(tenant["org"].id), "period": PERIOD},
    ).status_code == 201

    login_as(tenant["accountant"])
    resp = client.post(
        "/api/v1/reconciliation/results/bulk-approve",
        json={"result_ids": [str(r.id) for r in results]},
    )
    assert resp.status_code == 423
    for r in results:
        db_session.refresh(r)
        assert r.status == "pending_review"


def test_bulk_approve_duplicate_ids_ok(client, db_session, tenant):
    r = _make_results(db_session, tenant["supplier"], n=1)[0]
    login_as(tenant["accountant"])

    resp = client.post(
        "/api/v1/reconciliation/results/bulk-approve",
        json={"result_ids": [str(r.id), str(r.id)]},
    )
    assert resp.status_code == 200
    db_session.refresh(r)
    assert r.status == "confirmed"
