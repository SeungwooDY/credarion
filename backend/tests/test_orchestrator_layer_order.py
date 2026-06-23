"""Integration test: Layer 3 adjudicates a (po, material) group before the
aggregate fallback can mask it.

Guards the reorder that puts the discrepancy-aware Layer 3 ahead of the
always-"matched" aggregate layer. The scenario sits in the band where the two
layers disagree: quantities reconcile exactly, but the statement amount is ~0.8%
high — inside the aggregate layer's 1% amount tolerance (it would mark the group
"matched") yet outside Layer 3's 0.5% (it flags price_higher).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
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


def _seed_masking_scenario(db: Session) -> Supplier:
    """One imbalanced (po, material) group: qty reconciles, amount ~0.8% high."""
    org = Organization(name="Org", reporting_currency="RMB")
    db.add(org)
    db.flush()
    sup = Supplier(org_id=org.id, vendor_code="XFY201", name="丰裕达")
    db.add(sup)
    db.flush()
    # Disable the AI layer so the test is deterministic / offline.
    db.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))

    # 2 ERP delivery rows, same (po, material), price 10.00 -> qty 1000, amount 10000.
    for i, q in enumerate([Decimal("600"), Decimal("400")], start=1):
        db.add(ERPRecord(
            org_id=org.id, supplier_id=sup.id, po_number="428759",
            material_number="430*0412*0*001", quantity=q, po_price=Decimal("10.0000"),
            amount=q * Decimal("10.0000"), currency="RMB", grn_number=f"G{i}",
            grn_date=datetime(2026, 3, 10 + i), source_file="t.csv", raw_row={},
        ))

    stmt = SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f")
    db.add(stmt)
    db.flush()
    # 3 statement lines (imbalanced: 3 > 2) -> qty 1000, unit price 10.08 -> +0.8% amount.
    for q in (Decimal("300"), Decimal("300"), Decimal("400")):
        db.add(StatementLineItem(
            statement_id=stmt.id, po_number="428759", material_number="430*0412*0*001",
            quantity=q, unit_price=Decimal("10.0800"), amount=q * Decimal("10.0800"),
            raw_row={},
        ))
    db.commit()
    return sup


def test_layer3_adjudicates_before_aggregate_fallback(db_session: Session):
    sup = _seed_masking_scenario(db_session)

    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    assert run.status == "completed"

    results = (
        db_session.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run.id)
        .all()
    )
    summary = [(r.match_type, r.discrepancy_type) for r in results]

    # Layer 3 must adjudicate this group and flag the 0.8% amount gap...
    assert any(
        r.match_type == "multi_delivery" and r.discrepancy_type == "price_higher"
        for r in results
    ), f"expected a multi_delivery price_higher discrepancy; got {summary}"

    # ...and it must NOT be silently consumed as an always-matched aggregate row.
    assert not any(r.match_type == "aggregate" for r in results), \
        f"group was masked by the aggregate layer; got {summary}"
