"""Tests for the human review queue: approve/reject endpoints + sorted GET.

Covers the review-queue rework where nothing auto-matches — every result is
queued as ``pending_review`` and an accountant confirms or flags each one.
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


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_session():
    """In-memory SQLite database for testing."""
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
    match_type: str = "exact",
    status: str = "pending_review",
    confidence_score: int = 100,
    confidence_label: str = "Exact Match",
    sort_priority: int = 1,
    amount: float = 1000.0,
    discrepancy_note: str | None = None,
) -> ReconciliationResult:
    r = ReconciliationResult(
        run_id=run.id,
        supplier_id=supplier.id,
        period=PERIOD,
        match_type=match_type,
        status=status,
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        sort_priority=sort_priority,
        discrepancy_note=discrepancy_note,
        match_details={"amount": amount},
    )
    db.add(r)
    db.commit()
    return r


# ============================================================
# Approve
# ============================================================


def test_approve_happy_path(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run)

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/approve",
        json={"reviewer_id": "richard"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": str(r.id), "status": "confirmed"}

    db_session.refresh(r)
    assert r.status == "confirmed"
    assert r.reviewer_id == "richard"
    assert r.reviewed_at is not None


def test_approve_with_optional_note(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run)

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/approve",
        json={"reviewer_id": "richard", "note": "verified against PO"},
    )
    assert resp.status_code == 200
    db_session.refresh(r)
    assert r.resolution_note == "verified against PO"


def test_approve_not_found_returns_404(client):
    resp = client.post(
        f"/api/v1/reconciliation/{uuid.uuid4()}/approve",
        json={"reviewer_id": "richard"},
    )
    assert resp.status_code == 404


def test_approve_already_confirmed_returns_409(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run, status="confirmed")

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/approve",
        json={"reviewer_id": "richard"},
    )
    assert resp.status_code == 409


def test_approve_already_rejected_returns_409(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run, status="rejected")

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/approve",
        json={"reviewer_id": "richard"},
    )
    assert resp.status_code == 409


# ============================================================
# Reject
# ============================================================


def test_reject_happy_path(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run)

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/reject",
        json={"reviewer_id": "richard", "reason": "qty does not match GRN"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": str(r.id), "status": "rejected"}

    db_session.refresh(r)
    assert r.status == "rejected"
    assert r.reviewer_id == "richard"
    assert r.reviewed_at is not None
    assert r.discrepancy_note == "qty does not match GRN"


def test_reject_empty_reason_returns_400(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run)

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/reject",
        json={"reviewer_id": "richard", "reason": ""},
    )
    assert resp.status_code == 400


def test_reject_whitespace_reason_returns_400(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run)

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/reject",
        json={"reviewer_id": "richard", "reason": "   "},
    )
    assert resp.status_code == 400


def test_reject_not_found_returns_404(client):
    resp = client.post(
        f"/api/v1/reconciliation/{uuid.uuid4()}/reject",
        json={"reviewer_id": "richard", "reason": "missing"},
    )
    assert resp.status_code == 404


def test_reject_already_reviewed_returns_409(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    r = _make_result(db_session, supplier, run, status="confirmed")

    resp = client.post(
        f"/api/v1/reconciliation/{r.id}/reject",
        json={"reviewer_id": "richard", "reason": "changed my mind"},
    )
    assert resp.status_code == 409


# ============================================================
# Sorted review queue
# ============================================================


def test_review_queue_sorted_near_exact_before_fuzzy(client, db_session, supplier):
    """near_exact (priority 2) must appear before fuzzy (priority 3)."""
    run = _make_run(db_session, supplier)
    # Insert deliberately out of order.
    _make_result(db_session, supplier, run, match_type="fuzzy",
                 confidence_score=75, confidence_label="Probable Match",
                 sort_priority=3, amount=500.0)
    _make_result(db_session, supplier, run, match_type="unmatched",
                 status="unmatched", confidence_score=0,
                 confidence_label="No Match Found", sort_priority=6, amount=900.0)
    _make_result(db_session, supplier, run, match_type="near_exact",
                 confidence_score=92,
                 confidence_label="High Confidence — Small Discrepancy",
                 sort_priority=2, amount=100.0,
                 discrepancy_note="Small discrepancy detected. ...")
    _make_result(db_session, supplier, run, match_type="exact",
                 sort_priority=1, amount=50.0)

    resp = client.get(f"/api/v1/reconciliation/{supplier.id}/{PERIOD}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    priorities = [item["sort_priority"] for item in body]
    assert priorities == sorted(priorities)
    match_types = [item["match_type"] for item in body]
    assert match_types == ["exact", "near_exact", "fuzzy", "unmatched"]
    # near_exact comes strictly before fuzzy
    assert match_types.index("near_exact") < match_types.index("fuzzy")


def test_review_queue_amount_desc_within_group(client, db_session, supplier):
    """Within a sort_priority group, larger amounts come first."""
    run = _make_run(db_session, supplier)
    _make_result(db_session, supplier, run, match_type="exact", sort_priority=1, amount=10.0)
    _make_result(db_session, supplier, run, match_type="exact", sort_priority=1, amount=9000.0)
    _make_result(db_session, supplier, run, match_type="exact", sort_priority=1, amount=300.0)

    resp = client.get(f"/api/v1/reconciliation/{supplier.id}/{PERIOD}")
    assert resp.status_code == 200
    amounts = [item["amount"] for item in resp.json()]
    assert amounts == [9000.0, 300.0, 10.0]


def test_review_queue_exposes_review_fields(client, db_session, supplier):
    run = _make_run(db_session, supplier)
    _make_result(db_session, supplier, run, match_type="near_exact",
                 confidence_score=92,
                 confidence_label="High Confidence — Small Discrepancy",
                 sort_priority=2, discrepancy_note="Small discrepancy detected.")

    resp = client.get(f"/api/v1/reconciliation/{supplier.id}/{PERIOD}")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["confidence_score"] == 92
    assert item["confidence_label"] == "High Confidence — Small Discrepancy"
    assert item["sort_priority"] == 2
    assert item["discrepancy_note"] == "Small discrepancy detected."
    assert item["status"] == "pending_review"


def test_review_queue_no_run_returns_empty(client, supplier):
    resp = client.get(f"/api/v1/reconciliation/{supplier.id}/{PERIOD}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_review_queue_does_not_shadow_literal_routes(client):
    """The {supplier_id}/{period} catch-all must not swallow /runs, /results, etc."""
    # /runs/{bad uuid} should 422 (UUID parse), proving it hit the runs route.
    resp = client.get("/api/v1/reconciliation/runs/not-a-uuid")
    assert resp.status_code == 422
    # /results with a status filter should resolve to the list endpoint.
    resp = client.get("/api/v1/reconciliation/results?status=pending_review")
    assert resp.status_code == 200


# ============================================================
# Classification logic (_classify_review / _discrepancy_note)
# ============================================================

from datetime import datetime as _dt
from decimal import Decimal

from app.reconciliation import orchestrator as orch
from app.reconciliation.exact_match import MatchCandidate, MatchResult, StatementItem


def _match(match_type: str, qty_delta="0", price_delta="0", *, confidence="1.0",
           erp_qty="100", erp_price="10"):
    """Build a MatchResult with a statement line offset from ERP by the deltas."""
    erp = MatchCandidate(
        erp_id=1, po_number="428759", material_number="MAT001",
        quantity=Decimal(erp_qty), po_price=Decimal(erp_price),
        amount=Decimal(erp_qty) * Decimal(erp_price), grn_date=_dt(2026, 3, 15),
    )
    stmt = StatementItem(
        line_id=1, po_number="428759", material_number="MAT001",
        quantity=Decimal(erp_qty) + Decimal(qty_delta),
        unit_price=Decimal(erp_price) + Decimal(price_delta),
        amount=Decimal("1000"),
    )
    return MatchResult(
        erp=erp, statement=stmt, match_type=match_type,
        quantity_delta=Decimal(qty_delta), price_delta=Decimal(price_delta),
        amount_delta=Decimal("0"), status="matched", confidence=Decimal(confidence),
    )


def test_classify_exact_zero_delta():
    r = orch._classify_review(_match("exact", "0", "0"))
    assert r["match_type"] == "exact"
    assert r["status"] == "pending_review"
    assert r["confidence_score"] == 100
    assert r["confidence_label"] == "Exact Match"
    assert r["sort_priority"] == 1
    assert r["discrepancy_note"] is None


def test_classify_exact_small_delta_becomes_near_exact():
    # 0.2 units on 100 = 0.2% (within 0.5%)
    r = orch._classify_review(_match("exact", "0.2", "0"))
    assert r["match_type"] == "near_exact"
    assert r["confidence_score"] == 92
    assert r["confidence_label"] == "High Confidence — Small Discrepancy"
    assert r["sort_priority"] == 2
    assert r["discrepancy_note"].startswith("Small discrepancy detected.")
    assert "0.20%" in r["discrepancy_note"]
    assert r["discrepancy_note"].endswith("confirm with supplier.")


def test_classify_exact_large_delta_not_called_small():
    # 10 units on 100 = 10% (exceeds 0.5%): still priority 2, but accurate label.
    r = orch._classify_review(_match("exact", "10", "0"))
    assert r["match_type"] == "near_exact"
    assert r["sort_priority"] == 2
    assert r["confidence_score"] == 80
    assert r["confidence_label"] == "High Confidence — Discrepancy"
    # Must NOT be described as a small/rounding difference.
    assert "Small discrepancy" not in r["discrepancy_note"]
    assert "Exceeds the 0.5% tolerance" in r["discrepancy_note"]


def test_classify_near_exact_boundary_exactly_half_percent_is_small():
    # exactly 0.5% on both -> still "small" (<=0.5%)
    r = orch._classify_review(_match("exact", "0.5", "0.05"))
    assert r["confidence_score"] == 92
    assert r["confidence_label"] == "High Confidence — Small Discrepancy"


def test_classify_fuzzy():
    r = orch._classify_review(_match("fuzzy", "0", "0"))
    assert r["match_type"] == "fuzzy"
    assert r["confidence_score"] == 75
    assert r["confidence_label"] == "Probable Match"
    assert r["sort_priority"] == 3
    assert r["discrepancy_note"] is None


def test_classify_aggregate_and_multi_delivery_share_bucket():
    for mt in ("aggregate", "multi_delivery", "multi_po_dn"):
        r = orch._classify_review(_match(mt, "0", "0"))
        assert r["confidence_score"] == 70
        assert r["confidence_label"] == "Aggregated Match"
        assert r["sort_priority"] == 4


def test_classify_ai_uses_model_confidence():
    r = orch._classify_review(_match("ai", "0", "0", confidence="0.83"))
    assert r["match_type"] == "ai"
    assert r["confidence_score"] == 83
    assert r["confidence_label"] == "AI Suggested — Careful Review"
    assert r["sort_priority"] == 5


def test_discrepancy_note_exact_spec_format():
    # ERP 100 @ 10.0, supplier 100.2 @ 10.05 -> qty 0.20%, price 0.50%
    note = orch._discrepancy_note(_match("exact", "0.2", "0.05"), in_tolerance=True)
    assert note == (
        "Small discrepancy detected. "
        "Quantity: ERP 100 vs Supplier 100.2 (delta: 0.2 units, 0.20%). "
        "Price: ERP 10 vs Supplier 10.05 (delta: 0.0500, 0.50%). "
        "Likely rounding or minor data entry difference — confirm with supplier."
    )


def test_pct_safe_on_zero_base():
    assert orch._pct(Decimal("5"), Decimal("0")) == 0.0
    assert orch._pct(Decimal("5"), None) == 0.0
