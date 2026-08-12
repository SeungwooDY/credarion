"""Pairing scope: ERP rows are selected by their upload's period tag.

Monthly ERP exports contain overflowed dates (the pilot's March export
carries 135 February-dated receipts) and ERP bookings can trail supplier
records. Dates therefore never decide WHICH rows a run sees — the upload's
period tag does. Dates only combine rows and break ties. Legacy rows with no
tag fall back to their grn_date month.
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


def _org_and_supplier(db: Session) -> Supplier:
    org = Organization(name="Org", reporting_currency="RMB")
    db.add(org)
    db.flush()
    sup = Supplier(org_id=org.id, vendor_code="PCX201", name="鹏诚信测试")
    db.add(sup)
    db.flush()
    db.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))
    return sup


def _erp_row(db, sup, grn_no, qty, grn_date, tag, po="429250",
             material="125*1012*8*009", price="0.0350"):
    q, p = Decimal(qty), Decimal(price)
    db.add(ERPRecord(
        org_id=sup.org_id, supplier_id=sup.id, po_number=po,
        material_number=material, quantity=q, po_price=p,
        amount=q * p, currency="RMB", grn_number=grn_no,
        grn_date=grn_date, period=tag, source_file="t.csv", raw_row={},
    ))


def _stmt_with_line(db, sup, period, qty, delivery_date, po="429250",
                    material="125*1012*8*009", price="0.0350"):
    stmt = SupplierStatement(supplier_id=sup.id, period=period, file_url="f")
    db.add(stmt)
    db.flush()
    q, p = Decimal(qty), Decimal(price)
    db.add(StatementLineItem(
        statement_id=stmt.id, po_number=po, material_number=material,
        quantity=q, unit_price=p, amount=q * p,
        delivery_date=delivery_date, raw_row={},
    ))


def _results(db, run_id) -> list[ReconciliationResult]:
    return (
        db.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run_id)
        .all()
    )


def test_overflowed_date_pairs_via_tag(db_session: Session):
    """The PCX201 case: a February-dated receipt from the March export pairs
    with the March statement's claim — the tag puts it in scope."""
    sup = _org_and_supplier(db_session)
    _erp_row(db_session, sup, "5059315", "21000", datetime(2026, 2, 27, 11, 15),
             tag="2026-03")
    _stmt_with_line(db_session, sup, "2026-03", "21000", date(2026, 2, 26))
    db_session.commit()

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    assert run.status == "completed"
    results = _results(db_session, run.id)
    summary = [(r.match_type, r.discrepancy_type) for r in results]

    assert not any(r.discrepancy_type == "missing_from_erp" for r in results), summary
    assert any(r.match_type != "unmatched" and r.discrepancy_type is None
               for r in results), summary
    assert run.auto_match_rate == Decimal("100.00")


def test_other_months_upload_stays_out_of_scope(db_session: Session):
    """A receipt tagged to April never enters the March run — even when its
    grn_date falls inside March."""
    sup = _org_and_supplier(db_session)
    _erp_row(db_session, sup, "G-APR", "21000", datetime(2026, 3, 15), tag="2026-04")
    _stmt_with_line(db_session, sup, "2026-03", "21000", date(2026, 3, 15))
    db_session.commit()

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    results = _results(db_session, run.id)
    summary = [(r.match_type, r.discrepancy_type) for r in results]

    # The statement claim finds nothing: the April-tagged receipt is invisible.
    assert any(r.discrepancy_type == "missing_from_erp" for r in results), summary


def test_untagged_legacy_rows_fall_back_to_grn_date(db_session: Session):
    """Rows ingested before the tag existed (period NULL) keep working via
    their grn_date month."""
    sup = _org_and_supplier(db_session)
    _erp_row(db_session, sup, "G-LEG", "21000", datetime(2026, 3, 10), tag=None)
    _stmt_with_line(db_session, sup, "2026-03", "21000", date(2026, 3, 10))
    db_session.commit()

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    results = _results(db_session, run.id)
    assert not any(r.discrepancy_type for r in results)
    assert run.auto_match_rate == Decimal("100.00")
