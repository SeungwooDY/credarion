"""Tests for Layer 2: Fuzzy matching on normalized PO numbers."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.fuzzy_match import run_fuzzy_match
from app.reconciliation.normalization import (
    normalize_material_for_matching,
    normalize_po_for_matching,
)


def _erp(erp_id=1, po="428759", material="MAT001", **kw):
    defaults = dict(
        quantity=Decimal("100"), po_price=Decimal("10.00"),
        amount=Decimal("1000.00"), grn_date=datetime(2026, 3, 15),
        delivery_note=None,
    )
    defaults.update(kw)
    return MatchCandidate(erp_id=erp_id, po_number=po, material_number=material, **defaults)


def _stmt(line_id=1, po="428759", material="MAT001", **kw):
    defaults = dict(
        quantity=Decimal("100"), unit_price=Decimal("10.00"),
        amount=Decimal("1000.00"), delivery_date=None,
        delivery_note_ref=None,
    )
    defaults.update(kw)
    return StatementItem(line_id=line_id, po_number=po, material_number=material, **defaults)


class TestPONormalization:
    def test_leading_zeros(self):
        assert normalize_po_for_matching("0428759") == "428759"

    def test_dashes(self):
        assert normalize_po_for_matching("428-759") == "428759"

    def test_spaces(self):
        assert normalize_po_for_matching("428 759") == "428759"

    def test_combined(self):
        assert normalize_po_for_matching("0428-759") == "428759"

    def test_none(self):
        assert normalize_po_for_matching(None) is None

    def test_empty(self):
        assert normalize_po_for_matching("") is None


class TestMaterialNormalization:
    def test_uppercase(self):
        assert normalize_material_for_matching("mat001") == "MAT001"

    def test_leading_zeros(self):
        assert normalize_material_for_matching("00MAT001") == "MAT001"

    def test_dashes(self):
        assert normalize_material_for_matching("MAT-001") == "MAT001"

    def test_none(self):
        assert normalize_material_for_matching(None) is None


class TestFuzzyMatch:
    def test_leading_zero_po(self):
        """PO '0428759' should match '428759'."""
        erp = [_erp(po="428759")]
        stmt = [_stmt(po="0428759")]
        matches, unmatched_erp, unmatched_stmt = run_fuzzy_match(erp, stmt)
        assert len(matches) == 1
        assert matches[0].match_type == "fuzzy"
        assert matches[0].confidence == Decimal("0.90")

    def test_dashed_po(self):
        """PO '428-759' should match '428759'."""
        erp = [_erp(po="428759")]
        stmt = [_stmt(po="428-759")]
        matches, _, _ = run_fuzzy_match(erp, stmt)
        assert len(matches) == 1

    def test_material_case_diff(self):
        """Material 'mat001' should match 'MAT001' after normalization."""
        erp = [_erp(material="MAT001")]
        stmt = [_stmt(material="mat001")]
        matches, _, _ = run_fuzzy_match(erp, stmt)
        assert len(matches) == 1

    def test_no_match(self):
        """Completely different POs should not match."""
        erp = [_erp(po="111111")]
        stmt = [_stmt(po="999999")]
        matches, unmatched_erp, unmatched_stmt = run_fuzzy_match(erp, stmt)
        assert len(matches) == 0
        assert len(unmatched_erp) == 1
        assert len(unmatched_stmt) == 1

    def test_discrepancy_propagates(self):
        erp = [_erp(po="428759", quantity=Decimal("100"))]
        stmt = [_stmt(po="0428759", quantity=Decimal("110"))]
        matches, _, _ = run_fuzzy_match(erp, stmt)
        assert matches[0].status == "discrepancy"
        assert matches[0].discrepancy_type == "quantity_over"
