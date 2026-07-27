"""Missing-from-statement carryover across periods.

Suppliers re-include omitted items in the next month's statement. Unresolved
missing_from_statement receipts from prior periods join later runs as match
candidates; when they finally match, the prior period's discrepancy
auto-resolves (unless that period is signed off). Carryover items never
re-penalize the new period's match rate.
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
    PeriodSignoff,
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


def _seed(db: Session) -> tuple[Organization, Supplier, ERPRecord]:
    """One March receipt, no March statement → March run flags it missing."""
    org = Organization(name="Org", reporting_currency="RMB")
    db.add(org)
    db.flush()
    sup = Supplier(org_id=org.id, vendor_code="SDD201", name="奥雄电子")
    db.add(sup)
    db.flush()
    db.add(ReconciliationConfig(org_id=org.id, ai_layer_enabled=False))

    erp = ERPRecord(
        org_id=org.id, supplier_id=sup.id, po_number="428759",
        material_number="590*5166*8*003", quantity=Decimal("100"),
        po_price=Decimal("0.6575"), amount=Decimal("65.75"), currency="RMB",
        grn_number="G1", grn_date=datetime(2026, 3, 23),
        source_file="t.csv", raw_row={},
    )
    db.add(erp)
    # Empty March statement so the run has a statement side.
    db.add(SupplierStatement(supplier_id=sup.id, period="2026-03", file_url="f"))
    db.commit()
    return org, sup, erp


def _add_april_statement(db: Session, sup: Supplier, with_item: bool) -> None:
    stmt = SupplierStatement(supplier_id=sup.id, period="2026-04", file_url="f2")
    db.add(stmt)
    db.flush()
    lines = []
    if with_item:
        # The March receipt, finally claimed on the April statement.
        lines.append(dict(
            po_number="428759", material_number="590*5166*8*003",
            quantity=Decimal("100"), unit_price=Decimal("0.6575"),
            amount=Decimal("65.75"), delivery_date=datetime(2026, 3, 23).date(),
        ))
    # An ordinary April line with its own April receipt.
    lines.append(dict(
        po_number="500001", material_number="126*1715*9*006",
        quantity=Decimal("10"), unit_price=Decimal("2.00"),
        amount=Decimal("20.00"), delivery_date=datetime(2026, 4, 10).date(),
    ))
    for l in lines:
        db.add(StatementLineItem(statement_id=stmt.id, raw_row={}, **l))
    db.add(ERPRecord(
        org_id=sup.org_id, supplier_id=sup.id, po_number="500001",
        material_number="126*1715*9*006", quantity=Decimal("10"),
        po_price=Decimal("2.00"), amount=Decimal("20.00"), currency="RMB",
        grn_number="G2", grn_date=datetime(2026, 4, 10),
        source_file="t.csv", raw_row={},
    ))
    db.commit()


def _run(db: Session, sup: Supplier, period: str):
    return asyncio.run(run_reconciliation(sup.id, period, db))


class TestCarryover:
    def test_carryover_matches_and_autoresolves_prior(self, db_session: Session):
        org, sup, erp = _seed(db_session)
        march = _run(db_session, sup, "2026-03")
        prior = (
            db_session.query(ReconciliationResult)
            .filter_by(run_id=march.id, discrepancy_type="missing_from_statement")
            .one()
        )
        assert prior.status == "unmatched"

        _add_april_statement(db_session, sup, with_item=True)
        april = _run(db_session, sup, "2026-04")

        # The March receipt matched an April statement line, stamped with origin.
        april_results = (
            db_session.query(ReconciliationResult).filter_by(run_id=april.id).all()
        )
        carry = [r for r in april_results if (r.match_details or {}).get("carryover_from")]
        assert len(carry) == 1
        assert carry[0].match_details["carryover_from"] == "2026-03"
        assert carry[0].match_type != "unmatched"
        assert carry[0].erp_record_id == erp.id

        # Prior period's dead discrepancy closed by the system.
        db_session.refresh(prior)
        assert prior.status == "resolved"
        assert prior.resolved_by == "system"
        assert "2026-04" in (prior.resolution_note or "")

        # Both April statement lines matched → 100%.
        assert april.auto_match_rate == Decimal("100")

    def test_unmatched_carryover_does_not_penalize_new_period(self, db_session: Session):
        org, sup, erp = _seed(db_session)
        _run(db_session, sup, "2026-03")

        _add_april_statement(db_session, sup, with_item=False)
        april = _run(db_session, sup, "2026-04")

        # Still missing: surfaced as an issue, flagged as carryover…
        april_results = (
            db_session.query(ReconciliationResult).filter_by(run_id=april.id).all()
        )
        carry = [r for r in april_results if (r.match_details or {}).get("carryover_from")]
        assert len(carry) == 1
        assert carry[0].match_type == "unmatched"
        assert carry[0].discrepancy_type == "missing_from_statement"
        # …but April's own line matched, and the carryover item is excluded
        # from April's denominator (its own month already took the hit).
        assert april.auto_match_rate == Decimal("100")
        assert april.discrepancy_count == 1  # still visible as an issue

    def test_locked_prior_period_not_autoresolved(self, db_session: Session):
        org, sup, erp = _seed(db_session)
        march = _run(db_session, sup, "2026-03")
        prior = (
            db_session.query(ReconciliationResult)
            .filter_by(run_id=march.id, discrepancy_type="missing_from_statement")
            .one()
        )
        db_session.add(PeriodSignoff(
            org_id=org.id, period="2026-03", status="signed_off",
        ))
        db_session.commit()

        _add_april_statement(db_session, sup, with_item=True)
        april = _run(db_session, sup, "2026-04")

        # Match still happens in April…
        carry = [
            r for r in db_session.query(ReconciliationResult).filter_by(run_id=april.id)
            if (r.match_details or {}).get("carryover_from")
        ]
        assert len(carry) == 1 and carry[0].match_type != "unmatched"
        # …but the signed-off March result is left untouched.
        db_session.refresh(prior)
        assert prior.status == "unmatched"

    def test_resolved_prior_items_do_not_carry(self, db_session: Session):
        org, sup, erp = _seed(db_session)
        march = _run(db_session, sup, "2026-03")
        prior = (
            db_session.query(ReconciliationResult)
            .filter_by(run_id=march.id, discrepancy_type="missing_from_statement")
            .one()
        )
        prior.status = "resolved"
        prior.resolution_note = "manually dismissed"
        db_session.commit()

        _add_april_statement(db_session, sup, with_item=False)
        april = _run(db_session, sup, "2026-04")
        carry = [
            r for r in db_session.query(ReconciliationResult).filter_by(run_id=april.id)
            if (r.match_details or {}).get("carryover_from")
        ]
        assert carry == []

    def test_rerun_uses_latest_prior_run_only(self, db_session: Session):
        """A rerun of the prior period supersedes its first run's results."""
        org, sup, erp = _seed(db_session)
        _run(db_session, sup, "2026-03")
        # Second March run: same outcome, but ONLY its results should feed
        # carryover (no duplicates from the first run).
        _run(db_session, sup, "2026-03")

        _add_april_statement(db_session, sup, with_item=False)
        april = _run(db_session, sup, "2026-04")
        carry = [
            r for r in db_session.query(ReconciliationResult).filter_by(run_id=april.id)
            if (r.match_details or {}).get("carryover_from")
        ]
        assert len(carry) == 1
