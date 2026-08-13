"""Exact-quantity pairs claim their counterparts first (XFY201, 2026-08-12).

ERP had receipts of 13,728 and 9,984; the statement's date-combined groups
were 13,728, 9,984, and an extra 7,488 with no receipt. Greedy date-order
pairing let the 7,488 group grab the 9,984 receipt (phantom qty-under -2,496)
and left the true 9,984 group as a phantom missing-from-ERP. With the A0 pass
the exact pairs win and only the 7,488 surfaces — as missing_from_erp.
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


PO, MAT, PRICE = "430147", "590*3751*0*334", "1.1000"


def _setup(db: Session) -> Supplier:
    org = Organization(name="Org", reporting_currency="RMB")
    db.add(org)
    db.flush()
    sup = Supplier(org_id=org.id, vendor_code="XFY201", name="丰裕达测试")
    db.add(sup)
    db.flush()
    db.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))

    p = Decimal(PRICE)
    for grn_no, qty, d in (
        ("5065141", "13728", datetime(2026, 3, 26, 11, 25)),
        ("5065753", "9984", datetime(2026, 3, 29, 15, 6)),
    ):
        q = Decimal(qty)
        db.add(ERPRecord(
            org_id=org.id, supplier_id=sup.id, po_number=PO,
            material_number=MAT, quantity=q, po_price=p, amount=q * p,
            currency="RMB", grn_number=grn_no, grn_date=d, period="2026-03",
            source_file="t.csv", raw_row={},
        ))

    stmt = SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f")
    db.add(stmt)
    db.flush()
    # Three date-combined groups: 03-24 → 13,728; 03-25 → 7,488 (no receipt);
    # 03-26 → 9,984. Mirrors XFY201's real line structure in condensed form.
    groups = {
        date(2026, 3, 24): ["13000", "728"],
        date(2026, 3, 25): ["7000", "488"],
        date(2026, 3, 26): ["9000", "984"],
    }
    for d, qtys in groups.items():
        for qty in qtys:
            q = Decimal(qty)
            db.add(StatementLineItem(
                statement_id=stmt.id, po_number=PO, material_number=MAT,
                quantity=q, unit_price=p, amount=q * p,
                delivery_date=d, raw_row={},
            ))
    db.commit()
    return sup


def test_exact_pairs_win_extra_claim_goes_missing(db_session: Session):
    sup = _setup(db_session)
    run = asyncio.run(run_reconciliation(sup.id, "2026-03", db_session))
    assert run.status == "completed"

    results = (
        db_session.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run.id)
        .all()
    )
    flagged = [
        (r.discrepancy_type, float(r.quantity_delta) if r.quantity_delta is not None else None,
         (r.match_details or {}).get("stmt_combined_qty"))
        for r in results if r.discrepancy_type
    ]

    # No phantom qty-under: 13,728 and 9,984 pair exactly.
    assert not any(d and "quantity" in d for d, *_ in flagged), flagged
    # Exactly one issue: the 7,488 claim with no receipt.
    assert len(flagged) == 1, flagged
    d_type, _, combined = flagged[0]
    assert d_type == "missing_from_erp"
    assert combined == 7488.0
