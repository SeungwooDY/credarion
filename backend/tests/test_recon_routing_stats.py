"""Run-stats counting rules (ADR-0001 amendments).

The stats must stay robust against historical result shapes (aggregation-era
rows with duplicated statement_line_ids or one-sided constituents), so those
fixtures remain even though the aggregation layers themselves are retired.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.reconciliation.orchestrator import _compute_run_stats


class _FakeResult:
    """Bare-attribute stand-in for ReconciliationResult in stats tests."""

    def __init__(self, match_type="exact", statement_line_id=None, discrepancy_type=None,
                 match_details=None):
        self.match_type = match_type
        self.statement_line_id = statement_line_id
        self.discrepancy_type = discrepancy_type
        self.match_details = match_details


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

    def test_missing_from_statement_drags_rate_down(self):
        """ERP receipts absent from the statement are real issues (2026-07-26):
        they join the match-rate denominator, so an incomplete statement can
        never score 100%."""
        results = [
            _FakeResult(match_type="exact", statement_line_id=uuid.uuid4()),
            _FakeResult(match_type="unmatched", discrepancy_type="missing_from_statement"),
        ]
        stats = _compute_run_stats(results, total_statement=1)
        assert stats["matched_count"] == 1
        assert stats["unmatched_erp_count"] == 1
        # 1 matched / (1 statement line + 1 missing) = 50%
        assert stats["auto_match_rate"] == Decimal("50.0")

    def test_fully_matched_still_100(self):
        results = [
            _FakeResult(match_type="exact", statement_line_id=uuid.uuid4()),
            _FakeResult(match_type="exact", statement_line_id=uuid.uuid4()),
        ]
        stats = _compute_run_stats(results, total_statement=2)
        assert stats["auto_match_rate"] == Decimal("100")

    def test_carryover_excluded_from_denominator(self):
        """Carried-over missing receipts already penalized their origin
        period — they don't drag the new period's rate down."""
        results = [
            _FakeResult(match_type="exact", statement_line_id=uuid.uuid4()),
            _FakeResult(match_type="unmatched", discrepancy_type="missing_from_statement",
                        match_details={"carryover_from": "2026-03"}),
        ]
        stats = _compute_run_stats(results, total_statement=1)
        assert stats["unmatched_erp_count"] == 0
        assert stats["auto_match_rate"] == Decimal("100")

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
