"""Tenant-isolation tests for the reconciliation router.

The router authenticates every request but, before this fix, several endpoints
keyed on ``result_id`` / ``run_id`` / ``supplier_id`` performed no account
ownership check — any authenticated customer could read or mutate another
tenant's reconciliation data. These tests exercise the router as a NON-superuser
belonging to Account A and assert Account B's data is neither visible nor
mutable.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.auth_deps import get_current_user
from app.db import Base, get_db
from app.main import app
from app.models import (
    Account,
    Organization,
    ReconciliationResult,
    ReconciliationRun,
    Supplier,
    User,
)


PERIOD = "2026-03"


@pytest.fixture
def db_session():
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
    from sqlalchemy.pool import StaticPool

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    @compiles(PG_UUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):
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
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_tenant(db: Session, name: str) -> dict:
    """Create Account -> Organization -> Supplier -> Run -> Result, return handles."""
    account = Account(
        name=name, plan="growth", subscription_status="active"
    )
    db.add(account)
    db.flush()
    org = Organization(name=f"{name} Org", reporting_currency="RMB", account_id=account.id)
    db.add(org)
    db.flush()
    supplier = Supplier(org_id=org.id, vendor_code=f"V-{name}", name=f"{name} Supplier")
    db.add(supplier)
    db.flush()
    run = ReconciliationRun(
        supplier_id=supplier.id, period=PERIOD, status="completed",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    result = ReconciliationResult(
        run_id=run.id, supplier_id=supplier.id, period=PERIOD,
        match_type="near_exact", status="pending_review",
        discrepancy_type="quantity_over", confidence_score=80,
    )
    db.add(result)
    db.flush()
    user = User(
        account_id=account.id, email=f"user@{name}.test", hashed_password="x",
        full_name=f"{name} User", is_active=True, is_superuser=False, role="admin",
    )
    user.account = account
    db.add(user)
    db.commit()
    return {
        "account": account, "org": org, "supplier": supplier,
        "run": run, "result": result, "user": user,
    }


@pytest.fixture
def two_tenants(db_session: Session):
    a = _make_tenant(db_session, "acct-a")
    b = _make_tenant(db_session, "acct-b")
    return a, b


@pytest.fixture
def client_as_a(db_session: Session, two_tenants):
    """TestClient authenticated as Account A's non-superuser."""
    a, _ = two_tenants

    def _override_get_db():
        yield db_session

    def _override_user():
        return a["user"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_own_result_is_readable(client_as_a, two_tenants):
    a, _ = two_tenants
    resp = client_as_a.get(f"/api/v1/reconciliation/results/{a['result'].id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(a["result"].id)


def test_cross_tenant_result_blocked(client_as_a, two_tenants):
    _, b = two_tenants
    resp = client_as_a.get(f"/api/v1/reconciliation/results/{b['result'].id}")
    assert resp.status_code in (403, 404)


def test_cross_tenant_run_blocked(client_as_a, two_tenants):
    _, b = two_tenants
    resp = client_as_a.get(f"/api/v1/reconciliation/runs/{b['run'].id}")
    assert resp.status_code in (403, 404)


def test_cross_tenant_approve_blocked(client_as_a, two_tenants):
    _, b = two_tenants
    resp = client_as_a.post(
        f"/api/v1/reconciliation/{b['result'].id}/approve", json={}
    )
    assert resp.status_code in (403, 404)
    # And B's result must be untouched.
    assert b["result"].status == "pending_review"


def test_cross_tenant_resolve_blocked(client_as_a, two_tenants):
    _, b = two_tenants
    resp = client_as_a.put(
        f"/api/v1/reconciliation/results/{b['result'].id}/resolve",
        json={"resolution_note": "hijack"},
    )
    assert resp.status_code in (403, 404)


def test_bulk_resolve_rejects_cross_tenant_ids(client_as_a, two_tenants):
    a, b = two_tenants
    resp = client_as_a.post(
        "/api/v1/reconciliation/results/bulk-resolve",
        json={"result_ids": [str(a["result"].id), str(b["result"].id)],
              "resolution_note": "n"},
    )
    assert resp.status_code == 404


def test_list_runs_scoped_to_account(client_as_a, two_tenants):
    a, b = two_tenants
    resp = client_as_a.get("/api/v1/reconciliation/runs")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert str(a["run"].id) in ids
    assert str(b["run"].id) not in ids


def test_list_results_scoped_to_account(client_as_a, two_tenants):
    a, b = two_tenants
    resp = client_as_a.get("/api/v1/reconciliation/results")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert str(a["result"].id) in ids
    assert str(b["result"].id) not in ids


def test_summary_scoped_to_account(client_as_a, two_tenants):
    a, b = two_tenants
    resp = client_as_a.get("/api/v1/reconciliation/summary")
    assert resp.status_code == 200
    supplier_ids = {row["supplier_id"] for row in resp.json()}
    assert str(a["supplier"].id) in supplier_ids
    assert str(b["supplier"].id) not in supplier_ids
