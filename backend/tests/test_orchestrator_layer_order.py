"""Integration tests for the strict matching semantics (2026-07-31).

A pair requires identical PO + material + unit price with dates inside the
± window; quantity is the only field allowed to deviate. Rows are combined
only when ALL key fields are identical (both sides), and leftovers surface
as missing/extra — group totals are never netted.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import (
    ERPRecord,
    Organization,
    ReconciliationConfig,
    ReconciliationResult,
    StatementLineItem,
    Supplier,
    SupplierStatement,
)
from app.reconciliation.orchestrator import run_reconciliation


@pytest.fixture
def db_session():
    """In-memory SQLite database (PG types compiled down for sqlite)."""
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


def _org_and_supplier(db: Session, vendor_code: str) -> Supplier:
    org = Organization(name="Org", reporting_currency="RMB")
    db.add(org)
    db.flush()
    sup = Supplier(org_id=org.id, vendor_code=vendor_code, name="国威测试")
    db.add(sup)
    db.flush()
    # Disable the AI layer so the test is deterministic / offline.
    db.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))
    return sup


def _erp_row(db, sup, grn_no, qty, grn_date, po="428759", material="430*0412*0*001",
             price="10.0000"):
    q, p = Decimal(qty), Decimal(price)
    db.add(ERPRecord(
        org_id=sup.org_id, supplier_id=sup.id, po_number=po,
        material_number=material, quantity=q, po_price=p,
        amount=q * p, currency="RMB", grn_number=grn_no,
        grn_date=grn_date, source_file="t.csv", raw_row={},
    ))


def _stmt_line(db, stmt, qty, delivery_date, po="428759", material="430*0412*0*001",
               price="10.0000"):
    q, p = Decimal(qty), Decimal(price)
    db.add(StatementLineItem(
        statement_id=stmt.id, po_number=po, material_number=material,
        quantity=q, unit_price=p, amount=q * p,
        delivery_date=delivery_date, raw_row={},
    ))


def test_equal_totals_across_dates_are_not_netted(db_session: Session):
    """ERP has receipts on 3/10 and 3/20; the statement claims 3/10 and 3/25.
    Group totals agree exactly — the retired aggregation layer would have
    called this matched. Now the 3/10 rows pair and the two lone-date rows
    surface as missing on each side."""
    sup = _org_and_supplier(db_session, "GW001")
    _erp_row(db_session, sup, "G1", "100", datetime(2026, 3, 10))
    _erp_row(db_session, sup, "G2", "50", datetime(2026, 3, 20))
    stmt = SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f")
    db_session.add(stmt)
    db_session.flush()
    _stmt_line(db_session, stmt, "100", date(2026, 3, 10))
    _stmt_line(db_session, stmt, "50", date(2026, 3, 25))
    db_session.commit()

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    assert run.status == "completed"

    results = (
        db_session.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run.id)
        .all()
    )
    summary = [(r.match_type, r.status, r.discrepancy_type) for r in results]

    assert not any(r.match_type in ("multi_delivery", "aggregate") for r in results), \
        f"aggregation layers are retired: {summary}"

    matched = [r for r in results if r.match_type == "exact"]
    assert len(matched) == 1 and matched[0].discrepancy_type is None, summary
    assert sum(
        1 for r in results if r.discrepancy_type == "missing_from_statement"
    ) == 1, summary
    assert sum(
        1 for r in results if r.discrepancy_type == "missing_from_erp"
    ) == 1, summary

    # 1 matched stmt line / (2 stmt lines + 1 missing-from-statement) ≈ 33%
    assert run.matched_count == 1
    assert run.auto_match_rate == Decimal("33.33")


def test_clerk_forgot_to_combine_erp_rows(db_session: Session):
    """Two same-day, same-price GRN rows vs one combined statement line:
    ERP-side combining repairs the shape, so the group exact-matches with
    no phantom unmatched rows and a 100% rate."""
    sup = _org_and_supplier(db_session, "GW002")
    _erp_row(db_session, sup, "G1", "600", datetime(2026, 3, 6), po="428800",
             material="430*0500*0*001", price="5.0000")
    _erp_row(db_session, sup, "G2", "400", datetime(2026, 3, 6), po="428800",
             material="430*0500*0*001", price="5.0000")
    stmt = SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f")
    db_session.add(stmt)
    db_session.flush()
    _stmt_line(db_session, stmt, "1000", date(2026, 3, 6), po="428800",
               material="430*0500*0*001", price="5.0000")
    db_session.commit()

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    assert run.status == "completed"

    results = (
        db_session.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run.id)
        .all()
    )
    summary = [(r.match_type, r.status, r.discrepancy_type) for r in results]

    assert len(results) == 1, summary
    r = results[0]
    assert r.match_type == "exact" and r.discrepancy_type is None, summary
    # Combined-group fan-out metadata points back at both raw GRN rows.
    assert r.match_details.get("erp_combined_lines") == 2
    assert len(r.match_details.get("erp_combined_line_ids", [])) == 2
    assert r.match_details.get("erp_combined_qty") == 1000.0

    assert run.total_erp == 1  # combined count, mirroring total_statement
    assert run.discrepancy_count == 0
    assert run.matched_count == 1
    assert run.auto_match_rate == Decimal("100")


def test_price_mismatch_pairs_as_discrepancy_not_missing(db_session: Session):
    """Same PO+material+date but a different unit price: the pair is surfaced
    as a price discrepancy (both sides visible), not as two missing rows."""
    sup = _org_and_supplier(db_session, "GW003")
    _erp_row(db_session, sup, "G1", "100", datetime(2026, 3, 12), price="10.0000")
    stmt = SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f")
    db_session.add(stmt)
    db_session.flush()
    _stmt_line(db_session, stmt, "100", date(2026, 3, 12), price="10.0800")
    db_session.commit()

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    results = (
        db_session.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run.id)
        .all()
    )
    assert len(results) == 1
    r = results[0]
    assert r.discrepancy_type == "price_higher"
    assert r.erp_record_id is not None and r.statement_line_id is not None
