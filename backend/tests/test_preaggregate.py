"""Identical-row combining (both sides): combine only when PO, material,
date, and unit price ALL match — quantity is the only field allowed to
deviate (2026-07-31). The delivery-note ref is deliberately not part of the
key: two same-day deliveries carry different DNs yet the factory keys them
as one receipt."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.reconciliation.exact_match import MatchCandidate, StatementItem
from app.reconciliation.preaggregate import combine_erp_records, combine_statement_lines


def _line(
    line_id,
    po="428759",
    material="590*5166*8*003",
    qty="10",
    price="2.50",
    amount="25.00",
    delivery_date=date(2026, 3, 5),
    ref="DN-001",
) -> StatementItem:
    return StatementItem(
        line_id=line_id,
        po_number=po,
        material_number=material,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        amount=Decimal(amount),
        delivery_date=delivery_date,
        delivery_note_ref=ref,
    )


class TestCombine:
    def test_identical_lines_combine(self):
        items = [_line("a"), _line("b", qty="4", amount="10.00")]
        combined, groups = combine_statement_lines(items)

        assert len(combined) == 1
        c = combined[0]
        assert c.line_id == "a"  # primary = first occurrence
        assert c.quantity == Decimal("14")
        assert c.amount == Decimal("35.00")
        assert c.unit_price == Decimal("2.50")  # per-unit, never summed
        assert groups["a"].line_ids == ["a", "b"]
        assert groups["a"].quantity == Decimal("14")
        assert groups["a"].amount == Decimal("35.00")

    def test_three_way_combine(self):
        items = [_line("a"), _line("b"), _line("c")]
        combined, groups = combine_statement_lines(items)
        assert len(combined) == 1
        assert combined[0].quantity == Decimal("30")
        assert groups["a"].line_ids == ["a", "b", "c"]

    def test_equivalent_unit_price_representations_combine(self):
        # Decimal("2.5") == Decimal("2.50") — same per-unit price.
        items = [_line("a", price="2.5"), _line("b", price="2.50")]
        combined, _ = combine_statement_lines(items)
        assert len(combined) == 1

    def test_po_normalization_applies(self):
        # Excel float artifact and whitespace normalize to the same PO.
        items = [_line("a", po="428759"), _line("b", po=" 428759.0 ")]
        combined, _ = combine_statement_lines(items)
        assert len(combined) == 1


class TestKeepSeparate:
    def test_different_po(self):
        items = [_line("a"), _line("b", po="428760")]
        combined, groups = combine_statement_lines(items)
        assert len(combined) == 2
        assert groups == {}

    def test_different_date(self):
        items = [_line("a"), _line("b", delivery_date=date(2026, 3, 6))]
        combined, groups = combine_statement_lines(items)
        assert len(combined) == 2
        assert groups == {}

    def test_different_material(self):
        items = [_line("a"), _line("b", material="590*5166*8*004")]
        combined, _ = combine_statement_lines(items)
        assert len(combined) == 2

    def test_different_unit_price(self):
        # Stricter rule supersedes flagging: differing price → never combined.
        items = [_line("a"), _line("b", price="2.60", amount="26.00")]
        combined, groups = combine_statement_lines(items)
        assert len(combined) == 2
        assert groups == {}

    def test_missing_po_never_combines(self):
        items = [_line("a", po=None), _line("b", po=None)]
        combined, groups = combine_statement_lines(items)
        assert len(combined) == 2
        assert groups == {}


class TestDeliveryNoteNotInKey:
    def test_different_delivery_note_ref_still_combines(self):
        """Two atomic same-day deliveries have different DNs but the factory
        keys them as one receipt — so the DN must not split the group."""
        items = [_line("a"), _line("b", ref="DN-002")]
        combined, groups = combine_statement_lines(items)
        assert len(combined) == 1
        assert groups["a"].line_ids == ["a", "b"]


def _receipt(
    erp_id,
    po="428759",
    material="590*5166*8*003",
    qty="10",
    price="2.50",
    amount="25.00",
    grn_date=datetime(2026, 3, 5, 14, 30),
    dn="GRN-001",
) -> MatchCandidate:
    return MatchCandidate(
        erp_id=erp_id,
        po_number=po,
        material_number=material,
        quantity=Decimal(qty),
        po_price=Decimal(price),
        amount=Decimal(amount),
        grn_date=grn_date,
        delivery_note=dn,
    )


class TestCombineErp:
    def test_identical_receipts_combine(self):
        """The clerk forgot to key two same-day deliveries as one receipt —
        ERP-side combining repairs the shape."""
        records = [_receipt(1), _receipt(2, qty="4", amount="10.00", dn="GRN-002")]
        combined, groups = combine_erp_records(records)

        assert len(combined) == 1
        c = combined[0]
        assert c.erp_id == 1
        assert c.quantity == Decimal("14")
        assert c.amount == Decimal("35.00")
        assert c.po_price == Decimal("2.50")
        assert groups[1].line_ids == [1, 2]

    def test_time_of_day_does_not_split(self):
        records = [
            _receipt(1, grn_date=datetime(2026, 3, 5, 9, 0)),
            _receipt(2, grn_date=datetime(2026, 3, 5, 16, 45)),
        ]
        combined, _ = combine_erp_records(records)
        assert len(combined) == 1

    def test_different_grn_date_stays_separate(self):
        records = [_receipt(1), _receipt(2, grn_date=datetime(2026, 3, 6))]
        combined, groups = combine_erp_records(records)
        assert len(combined) == 2
        assert groups == {}

    def test_different_price_stays_separate(self):
        records = [_receipt(1), _receipt(2, price="2.60", amount="26.00")]
        combined, groups = combine_erp_records(records)
        assert len(combined) == 2
        assert groups == {}

    def test_erp_datetime_combines_with_stmt_date_shape(self):
        """ERP grn_date (datetime) and statement delivery_date (date) both
        reduce to a calendar date in the key, so an uncombined ERP pair and
        the pre-combined statement line meet 1:1 downstream."""
        from app.reconciliation.exact_match import run_exact_match

        erp_combined, _ = combine_erp_records([
            _receipt(1, qty="60", amount="150.00"),
            _receipt(2, qty="40", amount="100.00"),
        ])
        stmt = [_line("a", qty="100", amount="250.00")]

        matches, unmatched_erp, unmatched_stmt = run_exact_match(erp_combined, stmt)
        assert len(matches) == 1
        assert matches[0].status == "matched"
        assert not unmatched_erp and not unmatched_stmt


class TestPassthrough:
    def test_singles_unchanged_and_order_preserved(self):
        items = [
            _line("a", po="111111"),
            _line("b", po="222222"),
            _line("c", po="111111", delivery_date=date(2026, 3, 9)),
        ]
        combined, groups = combine_statement_lines(items)
        assert [c.line_id for c in combined] == ["a", "b", "c"]
        assert combined[0] is items[0]
        assert groups == {}

    def test_group_keeps_first_occurrence_position(self):
        items = [
            _line("a"),
            _line("x", po="999999"),
            _line("b"),  # combines with "a"
        ]
        combined, groups = combine_statement_lines(items)
        assert [c.line_id for c in combined] == ["a", "x"]
        assert groups["a"].line_ids == ["a", "b"]

    def test_none_dates_treated_as_equal(self):
        items = [_line("a", delivery_date=None), _line("b", delivery_date=None)]
        combined, _ = combine_statement_lines(items)
        assert len(combined) == 1

    def test_empty_input(self):
        combined, groups = combine_statement_lines([])
        assert combined == []
        assert groups == {}


class TestMatchingIntegration:
    def test_combined_lines_exact_match_consolidated_erp(self):
        """Two split supplier lines vs one consolidated ERP receipt: after
        pre-aggregation they exact-match with zero deltas."""
        from datetime import datetime

        from app.reconciliation.exact_match import MatchCandidate, run_exact_match

        stmt = [
            _line("a", qty="60", amount="150.00"),
            _line("b", qty="40", amount="100.00"),
        ]
        erp = [
            MatchCandidate(
                erp_id=1,
                po_number="428759",
                material_number="590*5166*8*003",
                quantity=Decimal("100"),
                po_price=Decimal("2.50"),
                amount=Decimal("250.00"),
                grn_date=datetime(2026, 3, 5),
            )
        ]

        combined, groups = combine_statement_lines(stmt)
        matches, unmatched_erp, unmatched_stmt = run_exact_match(erp, combined)

        assert len(matches) == 1
        m = matches[0]
        assert m.status == "matched"
        assert m.quantity_delta == 0
        assert m.amount_delta == 0
        assert m.statement.line_id == "a"
        assert groups["a"].line_ids == ["a", "b"]
        assert not unmatched_erp and not unmatched_stmt
