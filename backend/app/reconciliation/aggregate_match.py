"""Layer 2.5: Aggregate matching — groups unmatched lines and compares totals.

Handles the common real-world pattern where:
  - Supplier records individual deliveries (many small lines per PO)
  - ERP consolidates them into fewer, larger GRN receipts
  - The aggregated quantities and amounts match even though individual lines don't

Strategy (two passes):
  Pass 1: Group by PO number → compare aggregate qty/amount
  Pass 2: Group remaining by PO+material → compare aggregate qty/amount
  This catches cases where PO-level totals differ (cross-month spillover)
  but individual material groups still match.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.ingestion.cleaning import normalize_po_number
from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    _within_tolerance,
)


def _emit_aggregate_matches(
    erp_group: list[MatchCandidate],
    stmt_group: list[StatementItem],
    group_key: str,
    group_type: str,
    matched_erp_ids: set,
    matched_stmt_ids: set,
) -> list[MatchResult]:
    """Pair ERP records with statement lines for reporting, mark all as matched."""
    matches: list[MatchResult] = []

    erp_total_qty = sum(e.quantity for e in erp_group)
    erp_total_amt = sum(e.amount for e in erp_group)
    stmt_total_qty = sum(s.quantity for s in stmt_group)
    stmt_total_amt = sum(s.amount for s in stmt_group)

    base_details = {
        "layer": "2.5",
        "match_type": "aggregate",
        "group_type": group_type,
        "group_key": group_key,
        "erp_lines": len(erp_group),
        "stmt_lines": len(stmt_group),
        "erp_total_qty": str(erp_total_qty),
        "stmt_total_qty": str(stmt_total_qty),
        "erp_total_amt": str(erp_total_amt),
        "stmt_total_amt": str(stmt_total_amt),
    }

    remaining_stmt = list(stmt_group)
    for erp in erp_group:
        if not remaining_stmt:
            matches.append(MatchResult(
                erp=erp,
                statement=stmt_group[0],
                match_type="aggregate",
                quantity_delta=stmt_total_qty - erp_total_qty,
                price_delta=Decimal("0"),
                amount_delta=stmt_total_amt - erp_total_amt,
                status="matched",
                confidence=Decimal("0.85"),
                match_details=base_details,
            ))
        else:
            best_idx = min(
                range(len(remaining_stmt)),
                key=lambda i: abs(remaining_stmt[i].quantity - erp.quantity),
            )
            stmt = remaining_stmt.pop(best_idx)
            matches.append(MatchResult(
                erp=erp,
                statement=stmt,
                match_type="aggregate",
                quantity_delta=stmt.quantity - erp.quantity,
                price_delta=stmt.unit_price - erp.po_price,
                amount_delta=stmt.amount - erp.amount,
                status="matched",
                confidence=Decimal("0.85"),
                match_details=base_details,
            ))
        matched_erp_ids.add(erp.erp_id)

    for stmt in remaining_stmt:
        matches.append(MatchResult(
            erp=erp_group[0],
            statement=stmt,
            match_type="aggregate",
            quantity_delta=stmt.quantity - erp_group[0].quantity,
            price_delta=Decimal("0"),
            amount_delta=Decimal("0"),
            status="matched",
            confidence=Decimal("0.85"),
            match_details={**base_details, "note": "extra_statement_line_in_aggregate"},
        ))
        matched_stmt_ids.add(stmt.line_id)

    for e in erp_group:
        matched_erp_ids.add(e.erp_id)
    for s in stmt_group:
        matched_stmt_ids.add(s.line_id)

    return matches


def run_aggregate_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run aggregate matching on unmatched items.

    Pass 1: Group by PO, compare aggregate totals.
    Pass 2: Group remaining by PO+material, compare aggregate totals.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    matched_stmt_ids: set = set()

    # --- Pass 1: Group by PO ---
    erp_by_po: dict[str, list[MatchCandidate]] = defaultdict(list)
    for e in erp_records:
        po = normalize_po_number(e.po_number)
        if po:
            erp_by_po[po].append(e)

    stmt_by_po: dict[str, list[StatementItem]] = defaultdict(list)
    for s in statement_items:
        po = normalize_po_number(s.po_number)
        if po:
            stmt_by_po[po].append(s)

    common_pos = set(erp_by_po.keys()) & set(stmt_by_po.keys())
    for po in common_pos:
        erp_group = erp_by_po[po]
        stmt_group = stmt_by_po[po]

        erp_total_qty = sum(e.quantity for e in erp_group)
        erp_total_amt = sum(e.amount for e in erp_group)
        stmt_total_qty = sum(s.quantity for s in stmt_group)
        stmt_total_amt = sum(s.amount for s in stmt_group)

        qty_ok = _within_tolerance(erp_total_qty, stmt_total_qty, qty_tolerance_pct)
        amt_ok = _within_tolerance(erp_total_amt, stmt_total_amt, Decimal("1.0"))

        if not qty_ok and not amt_ok:
            continue

        matches.extend(_emit_aggregate_matches(
            erp_group, stmt_group, po, "po",
            matched_erp_ids, matched_stmt_ids,
        ))

    # --- Pass 2: Group remaining by PO+material ---
    remaining_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]
    remaining_stmt = [s for s in statement_items if s.line_id not in matched_stmt_ids]

    erp_by_po_mat: dict[tuple[str, str], list[MatchCandidate]] = defaultdict(list)
    for e in remaining_erp:
        po = normalize_po_number(e.po_number)
        mat = (e.material_number or "").strip()
        if po and mat:
            erp_by_po_mat[(po, mat)].append(e)

    stmt_by_po_mat: dict[tuple[str, str], list[StatementItem]] = defaultdict(list)
    for s in remaining_stmt:
        po = normalize_po_number(s.po_number)
        mat = (s.material_number or "").strip()
        if po and mat:
            stmt_by_po_mat[(po, mat)].append(s)

    common_keys = set(erp_by_po_mat.keys()) & set(stmt_by_po_mat.keys())
    for key in common_keys:
        erp_group = [e for e in erp_by_po_mat[key] if e.erp_id not in matched_erp_ids]
        stmt_group = [s for s in stmt_by_po_mat[key] if s.line_id not in matched_stmt_ids]
        if not erp_group or not stmt_group:
            continue

        erp_total_qty = sum(e.quantity for e in erp_group)
        erp_total_amt = sum(e.amount for e in erp_group)
        stmt_total_qty = sum(s.quantity for s in stmt_group)
        stmt_total_amt = sum(s.amount for s in stmt_group)

        qty_ok = _within_tolerance(erp_total_qty, stmt_total_qty, qty_tolerance_pct)
        amt_ok = _within_tolerance(erp_total_amt, stmt_total_amt, Decimal("1.0"))

        if not qty_ok and not amt_ok:
            continue

        matches.extend(_emit_aggregate_matches(
            erp_group, stmt_group, f"{key[0]}|{key[1]}", "po_material",
            matched_erp_ids, matched_stmt_ids,
        ))

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]
    unmatched_stmt = [s for s in statement_items if s.line_id not in matched_stmt_ids]

    return matches, unmatched_erp, unmatched_stmt
