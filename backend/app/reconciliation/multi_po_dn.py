"""Layer 3: Delivery note aggregation matching.

Groups ERP records and statement items by delivery note, then compares
aggregated quantities and amounts. Handles cases where a single delivery
note spans multiple PO lines.
"""
from __future__ import annotations

from dataclasses import field
from decimal import Decimal
from typing import Any

from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    _within_tolerance,
)


def _group_by_dn(
    items: list, dn_attr: str
) -> dict[str, list]:
    """Group items by delivery note, skipping items without one."""
    groups: dict[str, list] = {}
    for item in items:
        dn = getattr(item, dn_attr, None)
        if dn and str(dn).strip():
            key = str(dn).strip()
            groups.setdefault(key, []).append(item)
    return groups


def run_multi_po_dn_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 3 delivery note aggregation matching.

    Groups by delivery note, compares aggregated totals.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    erp_by_dn = _group_by_dn(erp_records, "delivery_note")
    stmt_by_dn = _group_by_dn(statement_items, "delivery_note_ref")

    matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    matched_stmt_ids: set = set()

    common_dns = set(erp_by_dn.keys()) & set(stmt_by_dn.keys())

    for dn in common_dns:
        erp_group = erp_by_dn[dn]
        stmt_group = stmt_by_dn[dn]

        # Aggregate ERP totals
        erp_total_qty = sum(e.quantity for e in erp_group)
        erp_total_amount = sum(e.amount for e in erp_group)

        # Aggregate statement totals
        stmt_total_qty = sum(s.quantity for s in stmt_group)
        stmt_total_amount = sum(s.amount for s in stmt_group)

        qty_delta = stmt_total_qty - erp_total_qty
        amount_delta = stmt_total_amount - erp_total_amount

        # Calculate average price for comparison
        erp_avg_price = (
            erp_total_amount / erp_total_qty if erp_total_qty else Decimal("0")
        )
        stmt_avg_price = (
            stmt_total_amount / stmt_total_qty if stmt_total_qty else Decimal("0")
        )
        price_delta = stmt_avg_price - erp_avg_price

        qty_ok = _within_tolerance(erp_total_qty, stmt_total_qty, qty_tolerance_pct)
        amount_ok = _within_tolerance(erp_total_amount, stmt_total_amount, price_tolerance_pct)

        if qty_ok and amount_ok:
            status = "matched"
            disc_type = None
        else:
            status = "discrepancy"
            if not qty_ok:
                disc_type = "quantity_over" if qty_delta > 0 else "quantity_under"
            else:
                disc_type = "price_higher" if amount_delta > 0 else "price_lower"

        # Create match results: pair ERP and statement items within the DN group
        # Primary pairing: zip by index, then handle remainders
        max_pairs = max(len(erp_group), len(stmt_group))
        for i in range(max_pairs):
            erp_item = erp_group[i] if i < len(erp_group) else None
            stmt_item = stmt_group[i] if i < len(stmt_group) else None

            if erp_item:
                matched_erp_ids.add(erp_item.erp_id)
            if stmt_item:
                matched_stmt_ids.add(stmt_item.line_id)

            # Per-item deltas (use aggregate status for the DN group)
            item_qty_delta = Decimal("0")
            item_price_delta = Decimal("0")
            item_amount_delta = Decimal("0")
            if erp_item and stmt_item:
                item_qty_delta = stmt_item.quantity - erp_item.quantity
                item_price_delta = stmt_item.unit_price - erp_item.po_price
                item_amount_delta = stmt_item.amount - erp_item.amount

            matches.append(MatchResult(
                erp=erp_item or erp_group[0],  # fallback for unpairable
                statement=stmt_item or stmt_group[0],
                match_type="multi_po_dn",
                quantity_delta=item_qty_delta,
                price_delta=item_price_delta,
                amount_delta=item_amount_delta,
                status=status,
                discrepancy_type=disc_type if status == "discrepancy" else None,
                confidence=Decimal("0.85"),
                match_details={
                    "layer": 3,
                    "delivery_note": dn,
                    "erp_count": len(erp_group),
                    "stmt_count": len(stmt_group),
                    "erp_total_qty": str(erp_total_qty),
                    "stmt_total_qty": str(stmt_total_qty),
                    "erp_total_amount": str(erp_total_amount),
                    "stmt_total_amount": str(stmt_total_amount),
                },
            ))

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]
    unmatched_stmt = [s for s in statement_items if s.line_id not in matched_stmt_ids]

    return matches, unmatched_erp, unmatched_stmt
