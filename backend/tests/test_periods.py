"""Derived-periods endpoint: union, ordering, lock flags, scoping."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import PeriodSignoff, ReconciliationRun, SupplierStatement
from app.periods import current_period, period_label, validate_period

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


# --- helpers -----------------------------------------------------------------


def test_validate_period():
    assert validate_period("2026-03") == "2026-03"
    for bad in ["2026-13", "2026-0", "202603", "2026-3", "", "abcd-ef"]:
        with pytest.raises(ValueError):
            validate_period(bad)


def test_period_label():
    assert period_label("2026-07") == "July 2026"
    assert period_label("2025-01") == "January 2025"


# --- endpoint ----------------------------------------------------------------


def _add_statement(db, supplier, period):
    db.add(
        SupplierStatement(supplier_id=supplier.id, period=period, file_url="x.xlsx")
    )
    db.commit()


def _add_run(db, supplier, period):
    db.add(
        ReconciliationRun(
            supplier_id=supplier.id, period=period, status="completed",
            started_at=datetime.utcnow(),
        )
    )
    db.commit()


def test_union_ordering_and_current_month(client, db_session, tenant):
    login_as(tenant["accountant"])
    _add_statement(db_session, tenant["supplier"], "2026-03")
    _add_run(db_session, tenant["supplier"], "2026-04")

    resp = client.get(f"/api/v1/periods?org_id={tenant['org'].id}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    periods = [r["period"] for r in rows]

    # Newest first, current month always present.
    assert periods == sorted(periods, reverse=True)
    assert current_period() in periods
    assert "2026-03" in periods and "2026-04" in periods

    by_period = {r["period"]: r for r in rows}
    assert by_period["2026-03"]["has_data"] is True
    assert by_period["2026-04"]["has_data"] is True  # run counts as data
    # Current month (no uploads in this test) has no data unless it collides
    # with a seeded period.
    if current_period() not in {"2026-03", "2026-04"}:
        assert by_period[current_period()]["has_data"] is False
    assert all(r["locked"] is False for r in rows)
    assert by_period["2026-03"]["label"] == "March 2026"


def test_locked_flag_and_signoff_only_period(client, db_session, tenant):
    login_as(tenant["accountant"])
    _add_statement(db_session, tenant["supplier"], "2026-02")
    db_session.add(
        PeriodSignoff(org_id=tenant["org"].id, period="2026-02", status="signed_off")
    )
    # A reopened sign-off for a period with no other data still lists it, unlocked.
    db_session.add(
        PeriodSignoff(org_id=tenant["org"].id, period="2026-01", status="reopened")
    )
    db_session.commit()

    rows = client.get(f"/api/v1/periods?org_id={tenant['org'].id}").json()
    by_period = {r["period"]: r for r in rows}
    assert by_period["2026-02"]["locked"] is True
    assert by_period["2026-01"]["locked"] is False
    assert by_period["2026-01"]["has_data"] is False


def test_org_scoping(client, db_session, tenant):
    other = seed_tenant(db_session, name="Other Account")
    _add_statement(db_session, other["supplier"], "2026-05")

    # Own org: does not include the other org's period.
    login_as(tenant["accountant"])
    periods = {
        r["period"]
        for r in client.get(f"/api/v1/periods?org_id={tenant['org'].id}").json()
    }
    assert "2026-05" not in periods

    # Other account's org id → 403 from enforce_org_scope (query-param org_id).
    resp = client.get(f"/api/v1/periods?org_id={other['org'].id}")
    assert resp.status_code == 403
