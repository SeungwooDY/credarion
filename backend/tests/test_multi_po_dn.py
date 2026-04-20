"""Tests for Layer 3: Delivery note aggregation matching."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.multi_po_dn import run_multi_po_dn_match


def _erp(erp_id=1, po="428759", material="MAT001", dn=None, **kw):
    defaults = dict(
        quantity=Decimal("100"), po_price=Decimal("10.00"),
        amount=Decimal("1000.00"), grn_date=datetime(2026, 3, 15),
    )
    defaults.update(kw)
    return MatchCandidate(
        erp_id=erp_id, po_number=po, material_number=material,
        delivery_note=dn, **defaults,
    )


def _stmt(line_id=1, po="428759", material="MAT001", dn_ref=None, **kw):
    defaults = dict(
        quantity=Decimal("100"), unit_price=Decimal("10.00"),
        amount=Decimal("1000.00"), delivery_date=None,
    )
    defaults.update(kw)
    return StatementItem(
        line_id=line_id, po_number=po, material_number=material,
        delivery_note_ref=dn_ref, **defaults,
    )


class TestMultiPoDnMatch:
    def test_single_dn_match(self):
        """Single delivery note with matching totals."""
        erp = [_erp(erp_id=1, dn="DN001")]
        stmt = [_stmt(line_id=1, dn_ref="DN001")]
        matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(erp, stmt)
        assert len(matches) == 1
        assert matches[0].match_type == "multi_po_dn"
        assert matches[0].status == "matched"

    def test_multi_line_dn(self):
        """Multiple ERP lines under one DN should aggregate."""
        erp = [
            _erp(erp_id=1, dn="DN001", quantity=Decimal("50"), amount=Decimal("500")),
            _erp(erp_id=2, dn="DN001", quantity=Decimal("50"), amount=Decimal("500")),
        ]
        stmt = [
            _stmt(line_id=1, dn_ref="DN001", quantity=Decimal("100"), amount=Decimal("1000")),
        ]
        matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(erp, stmt)
        assert len(matches) == 2  # one result per item in the larger group
        assert all(m.status == "matched" for m in matches)

    def test_dn_quantity_discrepancy(self):
        """Mismatched aggregated quantities should flag discrepancy."""
        erp = [_erp(erp_id=1, dn="DN001", quantity=Decimal("100"), amount=Decimal("1000"))]
        stmt = [_stmt(line_id=1, dn_ref="DN001", quantity=Decimal("120"), amount=Decimal("1200"))]
        matches, _, _ = run_multi_po_dn_match(erp, stmt)
        assert matches[0].status == "discrepancy"

    def test_no_dn_items_pass_through(self):
        """Items without delivery notes should be unmatched."""
        erp = [_erp(erp_id=1, dn=None)]
        stmt = [_stmt(line_id=1, dn_ref=None)]
        matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(erp, stmt)
        assert len(matches) == 0
        assert len(unmatched_erp) == 1
        assert len(unmatched_stmt) == 1

    def test_no_double_counting(self):
        """Each ERP/statement item should appear in results at most once."""
        erp = [
            _erp(erp_id=1, dn="DN001", quantity=Decimal("50"), amount=Decimal("500")),
            _erp(erp_id=2, dn="DN001", quantity=Decimal("50"), amount=Decimal("500")),
            _erp(erp_id=3, dn="DN002", quantity=Decimal("30"), amount=Decimal("300")),
        ]
        stmt = [
            _stmt(line_id=1, dn_ref="DN001", quantity=Decimal("100"), amount=Decimal("1000")),
            _stmt(line_id=2, dn_ref="DN002", quantity=Decimal("30"), amount=Decimal("300")),
        ]
        matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(erp, stmt)

        matched_erp_ids = {m.erp.erp_id for m in matches}
        matched_stmt_ids = {m.statement.line_id for m in matches}
        # All items should be matched
        assert matched_erp_ids == {1, 2, 3}
        assert matched_stmt_ids == {1, 2}
        assert len(unmatched_erp) == 0
        assert len(unmatched_stmt) == 0

    def test_partial_dn_match(self):
        """DN exists in ERP but not statement → items remain unmatched."""
        erp = [_erp(erp_id=1, dn="DN001")]
        stmt = [_stmt(line_id=1, dn_ref="DN999")]
        matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(erp, stmt)
        assert len(matches) == 0
        assert len(unmatched_erp) == 1
        assert len(unmatched_stmt) == 1
