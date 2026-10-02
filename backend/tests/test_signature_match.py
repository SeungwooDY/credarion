"""Tests for the suggest-only (quantity, unit price) pairing layer.

Covers the 2026-10-01 诚辉泰 (CHT201) work: suppliers whose PO/material never
overlap ERP but whose deliveries share an exact (quantity, unit_price). These
are surfaced as hints, never counted as matches.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.signature_match import run_signature_suggestions


def _erp(erp_id, qty, po_price, po="999999", material="X", grn_date=None):
    return MatchCandidate(
        erp_id=erp_id, po_number=po, material_number=material,
        quantity=Decimal(str(qty)), po_price=Decimal(str(po_price)),
        amount=Decimal("0"), grn_date=grn_date or datetime(2026, 7, 2),
    )


def _stmt(line_id, qty, unit_price, po="GW001B", material="box", delivery_date=None):
    return StatementItem(
        line_id=line_id, po_number=po, material_number=material,
        quantity=Decimal(str(qty)), unit_price=Decimal(str(unit_price)),
        amount=Decimal("0"), delivery_date=delivery_date,
    )


def test_matches_on_qty_and_price_despite_po_material_divergence():
    # Mirrors CHT201: PO/material differ, but qty+price are identical.
    erp = [_erp(1, 100, "8.778", po="432968", material="631*2646*4*002")]
    stmt = [_stmt(9, 100, "8.778", po="GW001B066612", material="普通箱")]
    out = run_signature_suggestions(erp, stmt)
    assert len(out) == 1
    assert out[0]["erp_id"] == 1
    assert out[0]["stmt_line_id"] == 9
    assert out[0]["confidence"] == 0.85


def test_no_suggestion_when_price_differs():
    erp = [_erp(1, 100, "8.778")]
    stmt = [_stmt(9, 100, "9.000")]
    assert run_signature_suggestions(erp, stmt) == []


def test_no_suggestion_when_qty_differs():
    erp = [_erp(1, 100, "8.778")]
    stmt = [_stmt(9, 101, "8.778")]
    assert run_signature_suggestions(erp, stmt) == []


def test_price_compared_on_po_price_not_unit_price():
    # unit_price on the ERP side is irrelevant; the engine (and this layer)
    # gate on po_price.
    erp = [_erp(1, 50, "3.8")]
    stmt = [_stmt(9, 50, "3.8")]
    assert len(run_signature_suggestions(erp, stmt)) == 1


def test_one_to_one_claiming():
    # Two statement lines, two ERP rows, all sharing one signature → each ERP
    # claimed once; two distinct suggestions.
    erp = [_erp(1, 10, "2.0"), _erp(2, 10, "2.0")]
    stmt = [_stmt(8, 10, "2.0"), _stmt(9, 10, "2.0")]
    out = run_signature_suggestions(erp, stmt)
    assert len(out) == 2
    assert {s["erp_id"] for s in out} == {1, 2}
    assert {s["stmt_line_id"] for s in out} == {8, 9}


def test_date_tiebreaker_picks_closest():
    # One statement line, two ERP rows with the same signature; the one with the
    # closest grn_date to the delivery date wins.
    erp = [
        _erp(1, 10, "2.0", grn_date=datetime(2026, 7, 20)),
        _erp(2, 10, "2.0", grn_date=datetime(2026, 7, 3)),
    ]
    stmt = [_stmt(9, 10, "2.0", delivery_date=datetime(2026, 7, 2))]
    out = run_signature_suggestions(erp, stmt)
    assert len(out) == 1
    assert out[0]["erp_id"] == 2  # closest date
    assert out[0]["confidence"] == 0.70  # collided signature → lower confidence


def test_missing_qty_or_price_skipped():
    erp = [_erp(1, 10, "2.0")]
    stmt = [StatementItem(
        line_id=9, po_number="x", material_number="y",
        quantity=None, unit_price=Decimal("2.0"), amount=Decimal("0"),
    )]
    assert run_signature_suggestions(erp, stmt) == []
