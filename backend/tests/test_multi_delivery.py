"""Tests for Layer 3: multi-delivery aggregation matching.

Layer 3 handles the case where the ERP logs one row per physical delivery, so a
single (po_number, material_number) can have several ERP rows in one month, while
the supplier statement combines (or differently splits) those deliveries. It
groups BOTH sides by (po_number, material_number), sums the quantities, and
compares the totals within the same ±0.5% tolerance used by Layers 1 and 2.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.multi_delivery import run_multi_delivery_match


def _erp(erp_id=1, po="428759", material="430*0412*0*001", qty="100",
         price="10.0000", amount=None, **kw):
    q = Decimal(qty)
    p = Decimal(price)
    return MatchCandidate(
        erp_id=erp_id,
        po_number=po,
        material_number=material,
        quantity=q,
        po_price=p,
        amount=Decimal(amount) if amount is not None else (q * p),
        grn_date=kw.pop("grn_date", datetime(2026, 3, 15)),
        delivery_note=kw.pop("delivery_note", None),
    )


def _stmt(line_id=1, po="428759", material="430*0412*0*001", qty="100",
          price="10.0000", amount=None, **kw):
    q = Decimal(qty)
    p = Decimal(price)
    return StatementItem(
        line_id=line_id,
        po_number=po,
        material_number=material,
        quantity=q,
        unit_price=p,
        amount=Decimal(amount) if amount is not None else (q * p),
        delivery_date=kw.pop("delivery_date", None),
        delivery_note_ref=kw.pop("delivery_note_ref", None),
    )


class TestMultiDeliveryAggregation:
    def test_multiple_erp_rows_match_combined_statement_line(self):
        """Three ERP delivery rows (300+400+300) match one combined stmt line (1000)."""
        erp = [
            _erp(erp_id=1, qty="300"),
            _erp(erp_id=2, qty="400"),
            _erp(erp_id=3, qty="300"),
        ]
        stmt = [_stmt(line_id=1, qty="1000")]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        assert matches, "expected the aggregated group to produce results"
        assert all(m.match_type == "multi_delivery" for m in matches)
        assert all(m.status == "matched" for m in matches)
        # Every ERP row and the statement line are consumed by the group
        assert {m.erp.erp_id for m in matches if m.erp is not None} == {1, 2, 3}
        assert 1 in {m.statement.line_id for m in matches if m.statement is not None}
        assert unmatched_erp == []
        assert unmatched_stmt == []

    def test_aggregates_both_sides_when_statement_also_split(self):
        """Real pattern: 2 ERP rows (1008+2376) vs 3 stmt lines (1008+1392+984), both sum 3384."""
        erp = [_erp(erp_id=1, qty="1008", price="2.5942"),
               _erp(erp_id=2, qty="2376", price="2.5942")]
        stmt = [_stmt(line_id=1, qty="1008", price="2.5942"),
                _stmt(line_id=2, qty="1392", price="2.5942"),
                _stmt(line_id=3, qty="984", price="2.5942")]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        assert all(m.status == "matched" for m in matches)
        assert {m.erp.erp_id for m in matches if m.erp is not None} == {1, 2}
        assert {m.statement.line_id for m in matches if m.statement is not None} == {1, 2, 3}
        # Amended contract: no row id appears twice across results.
        erp_ids = [m.erp.erp_id for m in matches if m.erp is not None]
        stmt_ids = [m.statement.line_id for m in matches if m.statement is not None]
        assert len(erp_ids) == len(set(erp_ids))
        assert len(stmt_ids) == len(set(stmt_ids))
        assert unmatched_erp == []
        assert unmatched_stmt == []

    def test_quantity_discrepancy_outside_tolerance(self):
        """ERP sums to 1000, statement to 1100 (10% over) -> quantity_over discrepancy."""
        erp = [_erp(erp_id=1, qty="600"), _erp(erp_id=2, qty="400")]
        stmt = [_stmt(line_id=1, qty="1100")]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        assert matches
        assert all(m.status == "discrepancy" for m in matches)
        # Amended contract: the group verdict lands exactly once (primary row);
        # constituents carry no discrepancy_type so groups aren't counted N times.
        assert [m.discrepancy_type for m in matches].count("quantity_over") == 1
        assert all(m.discrepancy_type in ("quantity_over", None) for m in matches)

    def test_quantity_under_discrepancy(self):
        """ERP sums to 1000, statement to 900 -> quantity_under discrepancy."""
        erp = [_erp(erp_id=1, qty="500"), _erp(erp_id=2, qty="500")]
        stmt = [_stmt(line_id=1, qty="900")]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        assert [m.discrepancy_type for m in matches].count("quantity_under") == 1
        assert all(m.status == "discrepancy" for m in matches)

    def test_within_half_percent_tolerance_is_matched(self):
        """A 0.4% total delta is inside ±0.5% -> matched, not a discrepancy."""
        erp = [_erp(erp_id=1, qty="500"), _erp(erp_id=2, qty="500")]  # 1000
        stmt = [_stmt(line_id=1, qty="1004")]  # +0.4%

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        assert matches
        assert all(m.status == "matched" for m in matches)

    def test_just_outside_half_percent_tolerance_is_discrepancy(self):
        """A 0.6% total delta is outside ±0.5% -> discrepancy."""
        erp = [_erp(erp_id=1, qty="500"), _erp(erp_id=2, qty="500")]  # 1000
        stmt = [_stmt(line_id=1, qty="1006")]  # +0.6%

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        assert all(m.status == "discrepancy" for m in matches)

    def test_price_inconsistency_across_deliveries_not_aggregated(self):
        """ERP rows for the same part with different po_price are NOT summed.

        Each ERP row is written as its own discrepancy carrying
        resolution_note='price inconsistency across deliveries'.
        """
        erp = [
            _erp(erp_id=1, qty="300", price="10.0000"),
            _erp(erp_id=2, qty="400", price="11.0000"),  # different price
            _erp(erp_id=3, qty="300", price="10.0000"),
        ]
        stmt = [_stmt(line_id=1, qty="1000")]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        # No aggregated "matched" result — the whole group is a discrepancy
        assert matches
        assert all(m.status == "discrepancy" for m in matches)
        erp_results = [m for m in matches if m.erp is not None]
        assert {m.erp.erp_id for m in erp_results} == {1, 2, 3}
        assert all(
            m.match_details.get("resolution_note") == "price inconsistency across deliveries"
            for m in erp_results
        )

    def test_erp_group_with_no_statement_counterpart_is_unmatched(self):
        """An ERP group with no matching statement key flows through as unmatched."""
        erp = [_erp(erp_id=1, po="999999", qty="300"),
               _erp(erp_id=2, po="999999", qty="300")]
        stmt = [_stmt(line_id=1, po="428759", qty="600")]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        # The orphan ERP group is returned for downstream (Layer 4 / tail) handling
        assert {e.erp_id for e in unmatched_erp} == {1, 2}
        # The lone statement line likewise has no ERP counterpart
        assert {s.line_id for s in unmatched_stmt} == {1}
        assert matches == []

    def test_po_number_normalization_floats_and_whitespace(self):
        """PO '428759.0' and ' 428759 ' normalize to the same group key."""
        erp = [_erp(erp_id=1, po="428759.0", qty="600"),
               _erp(erp_id=2, po="428759.0", qty="400")]
        stmt = [_stmt(line_id=1, po=" 428759 ", qty="1000")]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        assert matches
        assert all(m.status == "matched" for m in matches)
        assert unmatched_erp == []
        assert unmatched_stmt == []

    def test_no_double_counting_across_groups(self):
        """Each ERP/statement item appears in results at most once across groups."""
        erp = [
            _erp(erp_id=1, po="428759", material="MAT_A", qty="300"),
            _erp(erp_id=2, po="428759", material="MAT_A", qty="700"),
            _erp(erp_id=3, po="428760", material="MAT_B", qty="500"),
        ]
        stmt = [
            _stmt(line_id=1, po="428759", material="MAT_A", qty="1000"),
            _stmt(line_id=2, po="428760", material="MAT_B", qty="500"),
        ]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        erp_ids = [m.erp.erp_id for m in matches if m.erp is not None]
        stmt_ids = [m.statement.line_id for m in matches if m.statement is not None]
        assert len(erp_ids) == len(set(erp_ids)), "an ERP row appeared twice"
        assert len(stmt_ids) == len(set(stmt_ids)), "a statement line appeared twice"
        # both groups matched, nothing left over
        assert unmatched_erp == []
        assert unmatched_stmt == []

    def test_amount_discrepancy_flagged_when_quantities_match(self):
        """Quantities aggregate-equal but money is wrong -> discrepancy, not matched.

        Regression guard: a group must not be called 'matched' just because the
        quantities line up when the amounts are grossly different.
        """
        # ERP: 1000 units @ 10 = 10000 ; STMT: 1000 units @ 25 = 25000
        erp = [_erp(erp_id=1, qty="600", price="10.0000", amount="6000.00"),
               _erp(erp_id=2, qty="400", price="10.0000", amount="4000.00")]
        stmt = [_stmt(line_id=1, qty="1000", price="25.0000", amount="25000.00")]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        assert matches
        assert all(m.status == "discrepancy" for m in matches)
        primaries = [m.discrepancy_type for m in matches if m.discrepancy_type is not None]
        assert primaries == ["price_higher"]

    def test_price_inconsistency_with_multiple_statement_lines_no_data_loss(self):
        """A price-inconsistent group with several statement lines drops nothing."""
        erp = [_erp(erp_id=1, qty="300", price="10.0000"),
               _erp(erp_id=2, qty="400", price="11.0000")]  # inconsistent prices
        stmt = [_stmt(line_id=1, qty="300"),
                _stmt(line_id=2, qty="400")]

        matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(erp, stmt)

        seen_stmt = {m.statement.line_id for m in matches if m.statement is not None} | {s.line_id for s in unmatched_stmt}
        seen_erp = {m.erp.erp_id for m in matches if m.erp is not None} | {e.erp_id for e in unmatched_erp}
        assert seen_stmt == {1, 2}, "a statement line was silently dropped"
        assert seen_erp == {1, 2}, "an ERP row was silently dropped"

    def test_price_inconsistency_preserves_real_quantity_delta(self):
        """A price-inconsistent group that ALSO over-claims qty must not report zero delta."""
        erp = [_erp(erp_id=1, qty="300", price="10.0000"),
               _erp(erp_id=2, qty="400", price="11.0000")]  # inconsistent; ERP total 700
        stmt = [_stmt(line_id=1, qty="1000")]  # supplier claims 1000

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        assert any(m.quantity_delta != Decimal("0") for m in matches), \
            "real quantity gap was masked as zero"

    def test_group_verdict_lands_on_extra_statement_line(self):
        """SDD201 regression: supplier claims a delivery the ERP never received.

        ERP has one 2630-unit receipt; the statement has the same 2630 line PLUS
        an extra 51370-unit line. The quantity_over verdict and the +51370 delta
        must land on the extra statement line (erp=None), NOT on the paired row
        whose own quantities match — otherwise the review UI shows a row with
        equal quantities carrying a huge delta while the culprit reads 'matched'.
        """
        erp = [_erp(erp_id=1, qty="2630", price="0.1323", amount="347.95")]
        stmt = [
            _stmt(line_id=1, qty="2630", price="0.1323", amount="347.95"),
            _stmt(line_id=2, qty="51370", price="0.1323", amount="6796.25"),
        ]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        primary = [m for m in matches if m.discrepancy_type is not None]
        assert len(primary) == 1
        p = primary[0]
        assert p.discrepancy_type == "quantity_over"
        assert p.erp is None and p.statement.line_id == 2
        assert p.quantity_delta == Decimal("51370")
        # The paired 2630/2630 row is a plain constituent with zero deltas.
        paired = next(m for m in matches if m.erp is not None)
        assert paired.statement.line_id == 1
        assert paired.quantity_delta == Decimal("0")
        assert paired.discrepancy_type is None

    def test_group_verdict_lands_on_extra_erp_line(self):
        """Mirror case: ERP received more than the supplier claims (quantity_under).

        The verdict and negative delta land on the leftover ERP receipt.
        """
        erp = [
            _erp(erp_id=1, qty="1000"),
            _erp(erp_id=2, qty="400"),
        ]
        stmt = [_stmt(line_id=1, qty="1000")]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        primary = [m for m in matches if m.discrepancy_type is not None]
        assert len(primary) == 1
        p = primary[0]
        assert p.discrepancy_type == "quantity_under"
        assert p.statement is None and p.erp.erp_id == 2
        assert p.quantity_delta == Decimal("-400")

    def test_group_verdict_falls_back_to_first_pair_without_leftovers(self):
        """Equal line counts but drifting quantities: delta stays on the first pair."""
        erp = [_erp(erp_id=1, qty="600"), _erp(erp_id=2, qty="400")]
        stmt = [_stmt(line_id=1, qty="700"), _stmt(line_id=2, qty="400")]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        primary = [m for m in matches if m.discrepancy_type is not None]
        assert len(primary) == 1
        p = primary[0]
        assert p.erp is not None and p.statement is not None
        assert p.quantity_delta == Decimal("100")

    def test_match_details_carry_aggregate_totals(self):
        """A matched group records its aggregate totals for the review UI."""
        erp = [_erp(erp_id=1, qty="300"), _erp(erp_id=2, qty="700")]
        stmt = [_stmt(line_id=1, qty="1000")]

        matches, _, _ = run_multi_delivery_match(erp, stmt)

        d = matches[0].match_details
        assert d["match_type"] == "multi_delivery"
        assert Decimal(d["erp_total_qty"]) == Decimal("1000")
        assert Decimal(d["stmt_total_qty"]) == Decimal("1000")
        assert d["erp_lines"] == 2
        assert d["stmt_lines"] == 1
