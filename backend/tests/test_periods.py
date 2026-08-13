"""Derived-periods endpoint: union, ordering, lock flags, scoping, creation."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import PeriodSignoff, ReconciliationRun, SupplierStatement
from app.periods import (
    can_create_period,
    current_period,
    next_period,
    period_label,
    validate_period,
)

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


def test_next_period():
    assert next_period("2026-07") == "2026-08"
    assert next_period("2026-12") == "2027-01"


def test_can_create_period_window():
    # Current month and any past month: always creatable.
    assert can_create_period("2026-08", today=date(2026, 8, 9)) is True
    assert can_create_period("2026-07", today=date(2026, 8, 9)) is True
    assert can_create_period("2020-01", today=date(2026, 8, 9)) is True
    # Future months: creatable through December of next year.
    assert can_create_period("2026-09", today=date(2026, 8, 9)) is True
    assert can_create_period("2027-12", today=date(2026, 8, 9)) is True
    assert can_create_period("2028-01", today=date(2026, 8, 9)) is False
    # Year boundary: from December, next year is still "current year + 1".
    assert can_create_period("2027-12", today=date(2026, 12, 27)) is True
    assert can_create_period("2028-01", today=date(2026, 12, 27)) is False


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


def test_union_and_ordering(client, db_session, tenant):
    login_as(tenant["accountant"])
    _add_statement(db_session, tenant["supplier"], "2026-03")
    _add_run(db_session, tenant["supplier"], "2026-04")

    resp = client.get(f"/api/v1/periods?org_id={tenant['org'].id}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    periods = [r["period"] for r in rows]

    # Newest first; months are no longer auto-added, only derived from data.
    assert periods == sorted(periods, reverse=True)
    assert "2026-03" in periods and "2026-04" in periods
    assert set(periods) <= {"2026-03", "2026-04"}

    by_period = {r["period"]: r for r in rows}
    assert by_period["2026-03"]["has_data"] is True
    assert by_period["2026-04"]["has_data"] is True  # run counts as data
    assert all(r["locked"] is False for r in rows)
    assert by_period["2026-03"]["label"] == "March 2026"


def test_bootstrap_current_month_when_org_empty(client, db_session, tenant):
    # An org with no data/sign-offs at all still lists the current month.
    login_as(tenant["accountant"])
    rows = client.get(f"/api/v1/periods?org_id={tenant['org'].id}").json()
    assert [r["period"] for r in rows] == [current_period()]
    assert rows[0]["has_data"] is False


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


# --- creation ----------------------------------------------------------------


def _create(client, org_id, period):
    return client.post("/api/v1/periods", json={"org_id": str(org_id), "period": period})


def test_create_current_month(client, db_session, tenant):
    login_as(tenant["accountant"])
    # Seed some past data so the bootstrap path isn't what lists the new month.
    _add_statement(db_session, tenant["supplier"], "2026-03")

    resp = _create(client, tenant["org"].id, current_period())
    assert resp.status_code == 201, resp.text
    assert resp.json() == {
        "period": current_period(),
        "label": period_label(current_period()),
        "has_data": False,
        "locked": False,
    }

    rows = client.get(f"/api/v1/periods?org_id={tenant['org'].id}").json()
    by_period = {r["period"]: r for r in rows}
    assert by_period[current_period()]["has_data"] is False
    assert by_period[current_period()]["locked"] is False


def test_create_duplicate_conflicts(client, db_session, tenant):
    login_as(tenant["accountant"])
    assert _create(client, tenant["org"].id, current_period()).status_code == 201
    assert _create(client, tenant["org"].id, current_period()).status_code == 409

    # A period that exists via data also conflicts.
    _add_statement(db_session, tenant["supplier"], "2026-03")
    assert _create(client, tenant["org"].id, "2026-03").status_code == 409


def test_create_outside_window_rejected(client, tenant):
    login_as(tenant["accountant"])
    # Past months are now creatable; beyond December of next year is not.
    past = "2020-01"
    beyond_next_year = f"{date.today().year + 2}-01"
    assert _create(client, tenant["org"].id, past).status_code == 201
    assert _create(client, tenant["org"].id, beyond_next_year).status_code == 422
    assert _create(client, tenant["org"].id, "not-a-period").status_code == 422


def test_create_org_scoping(client, db_session, tenant):
    other = seed_tenant(db_session, name="Other Account")
    login_as(tenant["accountant"])
    resp = _create(client, other["org"].id, current_period())
    assert resp.status_code == 403
