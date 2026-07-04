"""Layer 3.5 aggregate fallback: emission dedupe (ADR-0001 amendment).

The fallback's gate/always-matched semantics are deliberately unchanged (known
debt, starved by Layer 3) — these tests pin the amended EMISSION contract:
no row id twice, group delta exactly once, loss-free coverage.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.reconciliation.aggregate_match import run_aggregate_match
from app.reconciliation.exact_match import MatchCandidate, StatementItem


def _erp(erp_id, po="500100", material="MAT_A", qty="100", price="10.00"):
    q, p = Decimal(qty), Decimal(price)
    return MatchCandidate(
        erp_id=erp_id, po_number=po, material_number=material,
        quantity=q, po_price=p, amount=q * p,
        grn_date=datetime(2026, 3, 10), delivery_note=None,
    )


def _stmt(line_id, po="500100", material="MAT_A", qty="100", price="10.00"):
    q, p = Decimal(qty), Decimal(price)
    return StatementItem(
        line_id=line_id, po_number=po, material_number=material,
        quantity=q, unit_price=p, amount=q * p,
        delivery_date=None, delivery_note_ref=None,
    )


def _no_duplicate_ids(matches):
    erp_ids = [m.erp.erp_id for m in matches if m.erp is not None]
    stmt_ids = [m.statement.line_id for m in matches if m.statement is not None]
    assert len(erp_ids) == len(set(erp_ids)), "an ERP row appeared in two results"
    assert len(stmt_ids) == len(set(stmt_ids)), "a statement line appeared in two results"


def test_stmt_heavy_group_no_duplicates_and_delta_once():
    """1 ERP (100) vs 3 stmt (30/30/40): perfect aggregate — regression for the
    original bug where deltas came out -60/-70/-70 and the ERP id tripled."""
    erp = [_erp(1, qty="100")]
    stmt = [_stmt(1, qty="30"), _stmt(2, qty="30"), _stmt(3, qty="40")]

    matches, unmatched_erp, unmatched_stmt = run_aggregate_match(erp, stmt)

    assert matches and unmatched_erp == [] and unmatched_stmt == []
    _no_duplicate_ids(matches)
    # Group delta (zero here) appears once; all other rows zero too.
    assert sum((m.quantity_delta for m in matches), Decimal("0")) == Decimal("0")
    primaries = [m for m in matches if m.match_details.get("role") == "primary"]
    assert len(primaries) == 1
    # Loss-free: every statement line shows up exactly once somewhere.
    assert {m.statement.line_id for m in matches if m.statement is not None} == {1, 2, 3}


def test_erp_heavy_group_no_duplicates():
    """3 ERP (30/30/40) vs 1 stmt (100): leftover ERP rows get statement=None."""
    erp = [_erp(1, qty="30"), _erp(2, qty="30"), _erp(3, qty="40")]
    stmt = [_stmt(1, qty="100")]

    matches, unmatched_erp, unmatched_stmt = run_aggregate_match(erp, stmt)

    assert matches and unmatched_erp == [] and unmatched_stmt == []
    _no_duplicate_ids(matches)
    assert {m.erp.erp_id for m in matches if m.erp is not None} == {1, 2, 3}
    leftovers = [m for m in matches if m.statement is None]
    assert len(leftovers) == 2
    assert all(m.quantity_delta == 0 and m.amount_delta == 0 for m in leftovers)


def test_group_delta_summation_equals_true_delta():
    """A within-tolerance nonzero group delta is recorded exactly once, so the
    sum over all result rows equals the true group delta (not N times it)."""
    # ERP 1000 @10 = 10000 vs stmt 3 lines totalling 1004 (=+0.4%, within 0.5% qty
    # tolerance and 1% amount tolerance) → accepted with a small nonzero delta.
    erp = [_erp(1, qty="1000")]
    stmt = [_stmt(1, qty="300"), _stmt(2, qty="300"), _stmt(3, qty="404")]

    matches, _, _ = run_aggregate_match(erp, stmt)

    assert matches
    _no_duplicate_ids(matches)
    total_qty_delta = sum((m.quantity_delta for m in matches), Decimal("0"))
    assert total_qty_delta == Decimal("4"), "group delta must appear exactly once"
