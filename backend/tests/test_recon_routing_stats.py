"""Symmetric _split_by_balance routing + run-stats counting rules (ADR-0001)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.orchestrator import _compute_run_stats, _split_by_balance


def _erp(erp_id, po="428759", material="MAT_A", qty="100"):
    q = Decimal(qty)
    return MatchCandidate(
        erp_id=erp_id, po_number=po, material_number=material,
        quantity=q, po_price=Decimal("10.00"), amount=q * Decimal("10.00"),
        grn_date=datetime(2026, 3, 10), delivery_note=None,
    )


def _stmt(line_id, po="428759", material="MAT_A", qty="100"):
    q = Decimal(qty)
    return StatementItem(
        line_id=line_id, po_number=po, material_number=material,
        quantity=q, unit_price=Decimal("10.00"), amount=q * Decimal("10.00"),
        delivery_date=None, delivery_note_ref=None,
    )


class _FakeResult:
    """Bare-attribute stand-in for ReconciliationResult in stats tests."""

    def __init__(self, match_type="exact", statement_line_id=None, discrepancy_type=None):
        self.match_type = match_type
        self.statement_line_id = statement_line_id
        self.discrepancy_type = discrepancy_type


class TestSplitByBalance:
    def test_erp_heavy_group_routed_to_aggregation(self):
        """3 ERP rows vs 1 stmt line (multi-day deliveries) → imbalanced.

        This is the direction the old 1.4x statement-heavy-only threshold
        missed — L1's tiebreaker used to consume it with a false discrepancy.
        """
        erp = [_erp(1, qty="300"), _erp(2, qty="300"), _erp(3, qty="400")]
        stmt = [_stmt(1, qty="1000")]

        bal_erp, bal_stmt, imb_erp, imb_stmt = _split_by_balance(erp, stmt)

        assert {e.erp_id for e in imb_erp} == {1, 2, 3}
        assert {s.line_id for s in imb_stmt} == {1}
        assert bal_erp == [] and bal_stmt == []

    def test_stmt_heavy_group_routed(self):
        erp = [_erp(1, qty="1000")]
        stmt = [_stmt(1, qty="300"), _stmt(2, qty="700")]

        _, _, imb_erp, imb_stmt = _split_by_balance(erp, stmt)
        assert {e.erp_id for e in imb_erp} == {1}
        assert {s.line_id for s in imb_stmt} == {1, 2}

    def test_small_imbalance_routed_no_threshold(self):
        """2v3 was below the old 1.4x threshold — now any inequality routes."""
        erp = [_erp(1), _erp(2)]
        stmt = [_stmt(1), _stmt(2), _stmt(3)]

        _, _, imb_erp, imb_stmt = _split_by_balance(erp, stmt)
        assert len(imb_erp) == 2 and len(imb_stmt) == 3

    def test_equal_counts_stay_balanced(self):
        erp = [_erp(1), _erp(2)]
        stmt = [_stmt(1), _stmt(2)]

        bal_erp, bal_stmt, imb_erp, imb_stmt = _split_by_balance(erp, stmt)
        assert len(bal_erp) == 2 and len(bal_stmt) == 2
        assert imb_erp == [] and imb_stmt == []

    def test_one_sided_group_stays_balanced(self):
        """Keys present on one side only aren't 'imbalanced' — they become
        L1/L2 leftovers and reach Layer 3 anyway."""
        erp = [_erp(1, po="999999")]
        stmt = [_stmt(1, po="428759")]

        bal_erp, bal_stmt, imb_erp, imb_stmt = _split_by_balance(erp, stmt)
        assert len(bal_erp) == 1 and len(bal_stmt) == 1
        assert imb_erp == [] and imb_stmt == []


class TestRunStats:
    def test_distinct_statement_lines_counted_once(self):
        """Duplicated statement_line_ids (historical aggregate bug shape) must
        not inflate matched_count or push the rate past 100%."""
        sid = uuid.uuid4()
        results = [
            _FakeResult(match_type="aggregate", statement_line_id=sid),
            _FakeResult(match_type="aggregate", statement_line_id=sid),
            _FakeResult(match_type="aggregate", statement_line_id=sid),
        ]
        stats = _compute_run_stats(results, total_statement=1)
        assert stats["matched_count"] == 1
        assert stats["auto_match_rate"] == Decimal("100")

    def test_rate_capped_at_100(self):
        results = [
            _FakeResult(match_type="exact", statement_line_id=uuid.uuid4()),
            _FakeResult(match_type="exact", statement_line_id=uuid.uuid4()),
        ]
        stats = _compute_run_stats(results, total_statement=1)  # inconsistent input
        assert stats["auto_match_rate"] == Decimal("100")

    def test_discrepancy_counted_once_per_group(self):
        """Constituent rows carry no discrepancy_type — only the primary counts."""
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        results = [
            _FakeResult(match_type="multi_delivery", statement_line_id=sid1,
                        discrepancy_type="quantity_over"),   # primary
            _FakeResult(match_type="multi_delivery", statement_line_id=sid2),  # constituent
            _FakeResult(match_type="multi_delivery"),                          # ERP-side constituent
        ]
        stats = _compute_run_stats(results, total_statement=2)
        assert stats["discrepancy_count"] == 1
        assert stats["matched_count"] == 2

    def test_unmatched_and_empty_statement(self):
        results = [
            _FakeResult(match_type="unmatched", discrepancy_type="missing_from_statement"),
            _FakeResult(match_type="unmatched", statement_line_id=uuid.uuid4(),
                        discrepancy_type="missing_from_erp"),
        ]
        stats = _compute_run_stats(results, total_statement=0)
        assert stats["unmatched_count"] == 2
        assert stats["unmatched_erp_count"] == 1
        assert stats["auto_match_rate"] == Decimal("0")
