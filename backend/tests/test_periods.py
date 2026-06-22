"""Tests for the accounting-period feature.

Covers: the period helpers (validate/label/ensure), the periods API
(create/list/uniqueness/validation), period stamping at GRN ingest, and
cross-period isolation in reconciliation (a run for one month never pulls
another month's ERP or statements).
"""
from __future__ import annotations

import tempfile
import uuid
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.ingestion.grn_ingestor import ingest_grn
from app.main import app
from app.models import (
    AccountingPeriod,
    ERPRecord,
    Organization,
    StatementLineItem,
    Supplier,
    SupplierStatement,
    ReconciliationConfig,
)
from app.periods import ensure_period, period_label, validate_period
from app.reconciliation.orchestrator import run_reconciliation


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_session():
    """In-memory SQLite database for testing (shared across the TestClient)."""
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
    s = Supplier(org_id=org.id, vendor_code="SDD201", name="奥雄电子")
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


# ============================================================
# Helpers
# ============================================================


def _make_grn_csv(rows: list[dict]) -> str:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        path = f.name
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    return path


def _grn_row(po: str, material: str, grn_no: str, grn_date: str) -> dict:
    return {
        "vend_no": "SDD201",
        "vend_name": "奥雄电子",
        "po_number": po,
        "material_number": material,
        "quantity": "100",
        "po_price": "0.50",
        "amount": "50.00",
        "currency": "RMB",
        "vat_rate": "13",
        "grn_number": grn_no,
        "grn_date": grn_date,
    }


def _add_erp(db: Session, org, supplier, period: str, po: str) -> None:
    db.add(
        ERPRecord(
            org_id=org.id,
            supplier_id=supplier.id,
            po_number=po,
            material_number="MAT-1",
            quantity=Decimal("100"),
            po_price=Decimal("0.50"),
            amount=Decimal("50.00"),
            currency="RMB",
            grn_number=f"GRN-{po}",
            grn_date=pd.Timestamp(f"{period}-15").to_pydatetime(),
            period=period,
            source_file="seed.csv",
            raw_row={},
        )
    )


def _add_statement(db: Session, supplier, period: str, n_lines: int) -> None:
    stmt = SupplierStatement(supplier_id=supplier.id, period=period, file_url="seed.xlsx")
    db.add(stmt)
    db.flush()
    for i in range(n_lines):
        db.add(
            StatementLineItem(
                statement_id=stmt.id,
                po_number=f"{period}-PO{i}",
                material_number="MAT-1",
                quantity=Decimal("100"),
                unit_price=Decimal("0.50"),
                amount=Decimal("50.00"),
                raw_row={},
            )
        )


# ============================================================
# Period helpers
# ============================================================


class TestPeriodHelpers:
    def test_validate_period_accepts_valid(self):
        assert validate_period("2026-07") == "2026-07"
        assert validate_period(" 2026-12 ") == "2026-12"

    @pytest.mark.parametrize("bad", ["2026-13", "2026-00", "26-07", "2026/07", "July", "", "2026-7"])
    def test_validate_period_rejects_invalid(self, bad):
        with pytest.raises(ValueError):
            validate_period(bad)

    def test_period_label(self):
        assert period_label("2026-07") == "July 2026"
        assert period_label("2026-01") == "January 2026"

    def test_ensure_period_creates_then_idempotent(self, db_session: Session, org: Organization):
        p1 = ensure_period(db_session, org.id, "2026-07")
        db_session.commit()
        assert p1.period == "2026-07"
        assert p1.label == "July 2026"
        assert p1.status == "open"

        p2 = ensure_period(db_session, org.id, "2026-07")
        db_session.commit()
        assert p2.id == p1.id
        assert db_session.query(AccountingPeriod).count() == 1


# ============================================================
# Periods API
# ============================================================


class TestPeriodsAPI:
    def test_create_and_list(self, client: TestClient, org: Organization):
        r = client.post("/api/v1/periods", json={"org_id": str(org.id), "period": "2026-07"})
        assert r.status_code == 201
        body = r.json()
        assert body["period"] == "2026-07"
        assert body["label"] == "July 2026"
        assert body["status"] == "open"

        # second month, then list newest-first
        client.post("/api/v1/periods", json={"org_id": str(org.id), "period": "2026-08"})
        listed = client.get(f"/api/v1/periods?org_id={org.id}").json()
        assert [p["period"] for p in listed] == ["2026-08", "2026-07"]

    def test_create_is_idempotent(self, client: TestClient, org: Organization):
        client.post("/api/v1/periods", json={"org_id": str(org.id), "period": "2026-07"})
        client.post("/api/v1/periods", json={"org_id": str(org.id), "period": "2026-07"})
        listed = client.get(f"/api/v1/periods?org_id={org.id}").json()
        assert len(listed) == 1

    def test_create_rejects_invalid_format(self, client: TestClient, org: Organization):
        r = client.post("/api/v1/periods", json={"org_id": str(org.id), "period": "2026-13"})
        assert r.status_code == 400


# ============================================================
# Period stamping at GRN ingest
# ============================================================


class TestGRNPeriodStamping:
    def test_ingest_stamps_upload_period_not_grn_date(
        self, db_session: Session, org: Organization
    ):
        # GRN dated in March, but uploaded into the July period → stays July.
        path = _make_grn_csv(
            [
                _grn_row("428759", "ABC*1234*5*678", "GRN-001", "2026-03-05"),
                _grn_row("428760", "DEF*5678*9*012", "GRN-002", "2026-03-06"),
            ]
        )
        result = ingest_grn(path, org.id, db_session, period="2026-07")
        assert result.status == "success"
        assert result.rows_ingested == 2

        rows = db_session.query(ERPRecord).all()
        assert len(rows) == 2
        assert {r.period for r in rows} == {"2026-07"}

        # The registry row was auto-created by ensure_period.
        period_row = (
            db_session.query(AccountingPeriod)
            .filter_by(org_id=org.id, period="2026-07")
            .one()
        )
        assert period_row.label == "July 2026"

    def test_ingest_rejects_invalid_period(self, db_session: Session, org: Organization):
        path = _make_grn_csv([_grn_row("428759", "ABC*1234*5*678", "GRN-001", "2026-03-05")])
        result = ingest_grn(path, org.id, db_session, period="bogus")
        assert result.status == "error"
        assert db_session.query(ERPRecord).count() == 0


# ============================================================
# Cross-period reconciliation isolation
# ============================================================


@pytest.mark.asyncio
async def test_reconciliation_only_pulls_its_own_period(
    db_session: Session, org: Organization, supplier: Supplier
):
    # Disable the AI layer so the run is deterministic and offline.
    db_session.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))

    # March: 2 ERP rows + a 2-line statement. April: 1 ERP row + a 1-line statement.
    _add_erp(db_session, org, supplier, "2026-03", "PO-M1")
    _add_erp(db_session, org, supplier, "2026-03", "PO-M2")
    _add_statement(db_session, supplier, "2026-03", n_lines=2)
    _add_erp(db_session, org, supplier, "2026-04", "PO-A1")
    _add_statement(db_session, supplier, "2026-04", n_lines=1)
    db_session.commit()

    run = await run_reconciliation(supplier.id, "2026-03", db_session)

    # Only March data is in scope — April's row/line must not bleed in.
    assert run.total_erp == 2
    assert run.total_statement == 2
