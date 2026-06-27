"""Tests for the /reconciliation/mismatches `include_matches` flag.

By default the endpoint returns only discrepancy rows. With include_matches=true
it also returns clean matched line items so the UI can show/export everything.
Summary counts stay mismatch-only; matches are counted in total_matches.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import (
    Organization,
    ReconciliationResult,
    ReconciliationRun,
    Supplier,
)


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


@pytest.fixture
def org(db_session: Session) -> Organization:
    o = Organization(name="Test Org", reporting_currency="RMB")
    db_session.add(o)
    db_session.commit()
    return o


@pytest.fixture
def supplier(db_session: Session, org: Organization) -> Supplier:
    s = Supplier(org_id=org.id, vendor_code="SDD201", name="奥雄电子有限公司")
    db_session.add(s)
    db_session.commit()
    return s


@pytest.fixture
def client(db_session: Session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


PERIOD = "2026-03"


def _make_run(db: Session, supplier: Supplier) -> ReconciliationRun:
    run = ReconciliationRun(
        supplier_id=supplier.id,
        period=PERIOD,
        status="completed",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    return run


def _make_result(
    db: Session,
    supplier: Supplier,
    run: ReconciliationRun,
    *,
    match_type: str,
    discrepancy_type: str | None,
) -> ReconciliationResult:
    r = ReconciliationResult(
        run_id=run.id,
        supplier_id=supplier.id,
        period=PERIOD,
        match_type=match_type,
        discrepancy_type=discrepancy_type,
        status="pending_review",
    )
    db.add(r)
    db.commit()
    return r


def _seed_one_of_each(db: Session, supplier: Supplier) -> ReconciliationRun:
    run = _make_run(db, supplier)
    _make_result(db, supplier, run, match_type="unmatched", discrepancy_type="missing_from_erp")
    _make_result(db, supplier, run, match_type="exact", discrepancy_type=None)
    return run


def test_default_excludes_matches(client, db_session, org, supplier):
    _seed_one_of_each(db_session, supplier)

    resp = client.get(
        "/api/v1/reconciliation/mismatches",
        params={"org_id": str(org.id), "period": PERIOD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["total_mismatches"] == 1
    assert entry["total_matches"] == 0
    assert len(entry["items"]) == 1
    assert all(i["discrepancy_type"] for i in entry["items"])


def test_include_matches_returns_matched_rows(client, db_session, org, supplier):
    _seed_one_of_each(db_session, supplier)

    resp = client.get(
        "/api/v1/reconciliation/mismatches",
        params={"org_id": str(org.id), "period": PERIOD, "include_matches": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    entry = body[0]
    # Summary counts stay mismatch-only; matches counted separately.
    assert entry["total_mismatches"] == 1
    assert entry["total_matches"] == 1
    assert len(entry["items"]) == 2
    matched = [i for i in entry["items"] if not i["discrepancy_type"]]
    assert len(matched) == 1
    assert matched[0]["match_type"] == "exact"


def test_supplier_with_only_matches_appears_when_included(client, db_session, org, supplier):
    """A supplier whose run has no discrepancies is hidden by default but shown
    once include_matches is set."""
    run = _make_run(db_session, supplier)
    _make_result(db_session, supplier, run, match_type="exact", discrepancy_type=None)

    base = {"org_id": str(org.id), "period": PERIOD}
    assert client.get("/api/v1/reconciliation/mismatches", params=base).json() == []

    resp = client.get(
        "/api/v1/reconciliation/mismatches",
        params={**base, "include_matches": "true"},
    )
    body = resp.json()
    assert len(body) == 1
    assert body[0]["total_mismatches"] == 0
    assert body[0]["total_matches"] == 1
