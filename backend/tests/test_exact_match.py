"""Tests for Layer 1: Exact matching engine."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.reconciliation.exact_match import (
    MatchCandidate,
    StatementItem,
    run_exact_match,
)


def _erp(
    erp_id: int = 1,
    po: str = "428759",
    material: str = "MAT001",
    qty: str = "100",
    price: str = "10.00",
    amount: str = "1000.00",
    grn_date: datetime | None = None,
    dn: str | None = None,
) -> MatchCandidate:
    return MatchCandidate(
        erp_id=erp_id,
        po_number=po,
        material_number=material,
        quantity=Decimal(qty),
        po_price=Decimal(price),
        amount=Decimal(amount),
        grn_date=grn_date or datetime(2026, 3, 15),
        delivery_note=dn,
    )


def _stmt(
    line_id: int = 1,
    po: str = "428759",
    material: str = "MAT001",
    qty: str = "100",
    price: str = "10.00",
    amount: str = "1000.00",
    delivery_date: datetime | None = None,
    dn_ref: str | None = None,
) -> StatementItem:
    return StatementItem(
        line_id=line_id,
        po_number=po,
        material_number=material,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        amount=Decimal(amount),
        delivery_date=delivery_date,
        delivery_note_ref=dn_ref,
    )


class TestExactMatch:
    def test_perfect_match(self):
        erp = [_erp()]
        stmt = [_stmt()]
        matches, unmatched_erp, unmatched_stmt = run_exact_match(erp, stmt)
        assert len(matches) == 1
        assert matches[0].status == "matched"
        assert matches[0].match_type == "exact"
        assert matches[0].quantity_delta == Decimal("0")
        assert matches[0].price_delta == Decimal("0")
        assert len(unmatched_erp) == 0
        assert len(unmatched_stmt) == 0

    def test_quantity_discrepancy(self):
        erp = [_erp(qty="100")]
        stmt = [_stmt(qty="105")]
        matches, _, _ = run_exact_match(erp, stmt)
        assert len(matches) == 1
        assert matches[0].status == "discrepancy"
        assert matches[0].discrepancy_type == "quantity_over"
        assert matches[0].quantity_delta == Decimal("5")

    def test_quantity_under(self):
        erp = [_erp(qty="100")]
        stmt = [_stmt(qty="90")]
        matches, _, _ = run_exact_match(erp, stmt)
        assert matches[0].discrepancy_type == "quantity_under"

    def test_price_discrepancy(self):
        erp = [_erp(price="10.00")]
        stmt = [_stmt(price="12.00")]
        matches, _, _ = run_exact_match(erp, stmt)
        assert matches[0].status == "discrepancy"
        assert matches[0].discrepancy_type == "price_higher"

    def test_price_lower(self):
        erp = [_erp(price="10.00")]
        stmt = [_stmt(price="8.00")]
        matches, _, _ = run_exact_match(erp, stmt)
        assert matches[0].discrepancy_type == "price_lower"

    def test_within_tolerance(self):
        """0.4% difference should be within 0.5% tolerance."""
        erp = [_erp(qty="1000")]
        stmt = [_stmt(qty="1004")]  # 0.4% diff
        matches, _, _ = run_exact_match(erp, stmt)
        assert matches[0].status == "matched"

    def test_at_tolerance_boundary(self):
        """0.5% exactly should still be within tolerance."""
        erp = [_erp(qty="1000")]
        stmt = [_stmt(qty="1005")]  # exactly 0.5%
        matches, _, _ = run_exact_match(erp, stmt)
        assert matches[0].status == "matched"

    def test_beyond_tolerance(self):
        """0.6% difference exceeds 0.5% tolerance."""
        erp = [_erp(qty="1000")]
        stmt = [_stmt(qty="1006")]  # 0.6%
        matches, _, _ = run_exact_match(erp, stmt)
        assert matches[0].status == "discrepancy"

    def test_unmatched_statement(self):
        erp = [_erp(po="428759")]
        stmt = [_stmt(po="999999")]
        matches, unmatched_erp, unmatched_stmt = run_exact_match(erp, stmt)
        assert len(matches) == 0
        assert len(unmatched_erp) == 1
        assert len(unmatched_stmt) == 1

    def test_missing_material_number(self):
        stmt = [_stmt(material=None)]
        erp = [_erp()]
        matches, _, unmatched_stmt = run_exact_match(erp, [stmt[0]])
        assert len(matches) == 0
        assert len(unmatched_stmt) == 1

    def test_duplicate_po_tiebreaker_by_date(self):
        """When multiple ERP records share PO+PN, pick closest grn_date."""
        erp1 = _erp(erp_id=1, grn_date=datetime(2026, 3, 1))
        erp2 = _erp(erp_id=2, grn_date=datetime(2026, 3, 20))
        stmt = [_stmt(delivery_date=datetime(2026, 3, 18))]

        matches, unmatched_erp, _ = run_exact_match([erp1, erp2], stmt)
        assert len(matches) == 1
        assert matches[0].erp.erp_id == 2  # closer date
        assert len(unmatched_erp) == 1

    def test_duplicate_po_tiebreaker_by_delivery_note(self):
        """Delivery note match takes priority over date proximity."""
        erp1 = _erp(erp_id=1, dn="DN001", grn_date=datetime(2026, 3, 20))
        erp2 = _erp(erp_id=2, dn="DN002", grn_date=datetime(2026, 3, 15))
        stmt = [_stmt(dn_ref="DN002", delivery_date=datetime(2026, 3, 20))]

        matches, _, _ = run_exact_match([erp1, erp2], stmt)
        assert matches[0].erp.erp_id == 2  # DN match wins over date

    def test_multiple_matches(self):
        erp = [
            _erp(erp_id=1, po="428759", material="MAT001"),
            _erp(erp_id=2, po="428760", material="MAT002"),
        ]
        stmt = [
            _stmt(line_id=1, po="428759", material="MAT001"),
            _stmt(line_id=2, po="428760", material="MAT002"),
        ]
        matches, unmatched_erp, unmatched_stmt = run_exact_match(erp, stmt)
        assert len(matches) == 2
        assert len(unmatched_erp) == 0
        assert len(unmatched_stmt) == 0

    def test_float_po_normalization(self):
        """PO '428759.0' should match '428759'."""
        erp = [_erp(po="428759")]
        stmt = [_stmt(po="428759.0")]
        matches, _, _ = run_exact_match(erp, stmt)
        assert len(matches) == 1
