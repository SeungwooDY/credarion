"""Carry-forward of human review state (marks/resolves) across re-runs.

Reconciliation now auto-reruns on every statement/GRN upload, so a re-run
must not wipe the accountant's marks and resolutions (it used to: every run
rebuilds result rows from scratch). Equivalent rows — same ERP record +
statement line + discrepancy type with unchanged deltas — inherit the
previous run's review state; rows whose underlying data changed do not.
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


def _setup_discrepancy(db: Session) -> Supplier:
    """One ERP receipt of 100 vs a statement claim of 90 → qty discrepancy."""
    org = Organization(name="Org", reporting_currency="RMB")
    db.add(org)
    db.flush()
    sup = Supplier(org_id=org.id, vendor_code="GW100", name="国威测试")
    db.add(sup)
    db.flush()
    db.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))

    q, p = Decimal("100"), Decimal("10.0000")
    db.add(ERPRecord(
        org_id=org.id, supplier_id=sup.id, po_number="428759",
        material_number="430*0412*0*001", quantity=q, po_price=p,
        amount=q * p, currency="RMB", grn_number="G1",
        grn_date=datetime(2026, 3, 10), source_file="t.csv", raw_row={},
    ))
    stmt = SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f")
    db.add(stmt)
    db.flush()
    db.add(StatementLineItem(
        statement_id=stmt.id, po_number="428759",
        material_number="430*0412*0*001", quantity=Decimal("90"),
        unit_price=p, amount=Decimal("90") * p,
        delivery_date=date(2026, 3, 10), raw_row={},
    ))
    db.commit()
    return sup


def _discrepancy_row(db: Session, run_id) -> ReconciliationResult:
    row = (
        db.query(ReconciliationResult)
        .filter(
            ReconciliationResult.run_id == run_id,
            ReconciliationResult.discrepancy_type.isnot(None),
        )
        .one()
    )
    return row


def test_mark_carries_to_next_run(db_session: Session):
    sup = _setup_discrepancy(db_session)
    run1 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row1 = _discrepancy_row(db_session, run1.id)

    row1.marked_discrepancy_reason = "Supplier over-claims"
    row1.marked_discrepancy_by = "richard@credarion.com"
    row1.marked_discrepancy_at = datetime(2026, 8, 5, 12, 0, 0)
    db_session.commit()

    run2 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row2 = _discrepancy_row(db_session, run2.id)

    assert row2.id != row1.id
    assert row2.marked_discrepancy_reason == "Supplier over-claims"
    assert row2.marked_discrepancy_by == "richard@credarion.com"
    assert row2.marked_discrepancy_at == row1.marked_discrepancy_at
    # Marking is orthogonal to resolution: the row stays open.
    assert row2.status != "resolved"


def test_resolution_carries_to_next_run(db_session: Session):
    sup = _setup_discrepancy(db_session)
    run1 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row1 = _discrepancy_row(db_session, run1.id)

    row1.status = "resolved"
    row1.resolution_note = "Short delivery confirmed with supplier"
    row1.resolved_by = "richard@credarion.com"
    row1.resolved_at = datetime(2026, 8, 6, 9, 0, 0)
    db_session.commit()

    run2 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row2 = _discrepancy_row(db_session, run2.id)

    assert row2.status == "resolved"
    assert row2.resolution_note == "Short delivery confirmed with supplier"
    assert row2.resolved_by == "richard@credarion.com"


def test_no_carry_when_underlying_data_changed(db_session: Session):
    sup = _setup_discrepancy(db_session)
    run1 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row1 = _discrepancy_row(db_session, run1.id)

    row1.marked_discrepancy_reason = "Qty mismatch"
    row1.status = "resolved"
    row1.resolution_note = "ok"
    db_session.commit()

    # The supplier corrects their claim (90 → 80): the delta changes, so the
    # old judgement no longer applies and must NOT be carried.
    line = db_session.query(StatementLineItem).one()
    line.quantity = Decimal("80")
    line.amount = Decimal("80") * line.unit_price
    db_session.commit()

    run2 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row2 = _discrepancy_row(db_session, run2.id)

    assert row2.marked_discrepancy_reason is None
    assert row2.status != "resolved"
    assert row2.resolution_note is None


def test_carry_survives_chained_runs(db_session: Session):
    """Mark on run 1 → runs 2 and 3 both keep it (each run copies from the
    previous completed run, so the state chains forward)."""
    sup = _setup_discrepancy(db_session)
    run1 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row1 = _discrepancy_row(db_session, run1.id)
    row1.marked_discrepancy_reason = "chained"
    db_session.commit()

    asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    run3 = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    row3 = _discrepancy_row(db_session, run3.id)
    assert row3.marked_discrepancy_reason == "chained"
