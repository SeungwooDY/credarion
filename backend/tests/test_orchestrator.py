"""Tests for the reconciliation orchestrator (end-to-end through all layers)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.orchestrator import _period_date_range


class TestPeriodDateRange:
    def test_standard_month(self):
        start, end = _period_date_range("2026-03")
        assert start == datetime(2026, 3, 1)
        assert end.day == 31
        assert end.month == 3

    def test_february(self):
        start, end = _period_date_range("2026-02")
        assert start == datetime(2026, 2, 1)
        assert end.day == 28

    def test_leap_year(self):
        start, end = _period_date_range("2024-02")
        assert end.day == 29


class TestOrchestratorWaterfall:
    """Test the waterfall logic using the individual layer functions directly."""

    def test_exact_then_fuzzy(self):
        """Items matched in Layer 1 should not appear in Layer 2."""
        from app.reconciliation.exact_match import run_exact_match
        from app.reconciliation.fuzzy_match import run_fuzzy_match

        erp = [
            MatchCandidate(
                erp_id=1, po_number="428759", material_number="MAT001",
                quantity=Decimal("100"), po_price=Decimal("10"),
                amount=Decimal("1000"), grn_date=datetime(2026, 3, 15),
            ),
            MatchCandidate(
                erp_id=2, po_number="428760", material_number="MAT002",
                quantity=Decimal("50"), po_price=Decimal("20"),
                amount=Decimal("1000"), grn_date=datetime(2026, 3, 15),
            ),
        ]
        stmt = [
            StatementItem(
                line_id=1, po_number="428759", material_number="MAT001",
                quantity=Decimal("100"), unit_price=Decimal("10"),
                amount=Decimal("1000"),
            ),
            StatementItem(
                line_id=2, po_number="0428760", material_number="mat002",
                quantity=Decimal("50"), unit_price=Decimal("20"),
                amount=Decimal("1000"),
            ),
        ]

        # Layer 1
        l1_matches, unmatched_erp, unmatched_stmt = run_exact_match(erp, stmt)
        assert len(l1_matches) == 1  # Only exact match on 428759

        # Layer 2 receives only unmatched
        l2_matches, unmatched_erp, unmatched_stmt = run_fuzzy_match(
            unmatched_erp, unmatched_stmt
        )
        assert len(l2_matches) == 1  # Fuzzy matches 0428760 → 428760
        assert len(unmatched_erp) == 0
        assert len(unmatched_stmt) == 0

    def test_all_matched_in_layer1(self):
        """If Layer 1 matches everything, Layer 2 gets empty lists."""
        from app.reconciliation.exact_match import run_exact_match
        from app.reconciliation.fuzzy_match import run_fuzzy_match

        erp = [
            MatchCandidate(
                erp_id=1, po_number="428759", material_number="MAT001",
                quantity=Decimal("100"), po_price=Decimal("10"),
                amount=Decimal("1000"), grn_date=datetime(2026, 3, 15),
            ),
        ]
        stmt = [
            StatementItem(
                line_id=1, po_number="428759", material_number="MAT001",
                quantity=Decimal("100"), unit_price=Decimal("10"),
                amount=Decimal("1000"),
            ),
        ]

        l1_matches, unmatched_erp, unmatched_stmt = run_exact_match(erp, stmt)
        assert len(l1_matches) == 1

        l2_matches, _, _ = run_fuzzy_match(unmatched_erp, unmatched_stmt)
        assert len(l2_matches) == 0
