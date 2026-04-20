"""Layer 2: Fuzzy match on normalized PO numbers.

Handles cases where PO numbers differ by leading zeros, dashes, or spaces
but represent the same order.
"""
from __future__ import annotations

from decimal import Decimal

from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    _classify_discrepancy,
    _pick_best_erp,
    _within_tolerance,
)
from app.reconciliation.normalization import (
    normalize_material_for_matching,
    normalize_po_for_matching,
)


def _fuzzy_key(po: str | None, material: str | None) -> tuple[str, str] | None:
    """Build a fuzzy-normalized (po, material) key."""
    norm_po = normalize_po_for_matching(po)
    norm_mat = normalize_material_for_matching(material)
    if norm_po is None or norm_mat is None:
        return None
    return (norm_po, norm_mat)


def run_fuzzy_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 2 fuzzy matching on unmatched items from Layer 1.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    # Build fuzzy ERP lookup
    erp_lookup: dict[tuple[str, str], list[MatchCandidate]] = {}
    for erp in erp_records:
        key = _fuzzy_key(erp.po_number, erp.material_number)
        if key is not None:
            erp_lookup.setdefault(key, []).append(erp)

    matches: list[MatchResult] = []
    unmatched_stmt: list[StatementItem] = []
    matched_erp_ids: set = set()

    for stmt in statement_items:
        key = _fuzzy_key(stmt.po_number, stmt.material_number)
        if key is None or key not in erp_lookup:
            unmatched_stmt.append(stmt)
            continue

        available = [e for e in erp_lookup[key] if e.erp_id not in matched_erp_ids]
        if not available:
            unmatched_stmt.append(stmt)
            continue

        erp = _pick_best_erp(available, stmt)
        matched_erp_ids.add(erp.erp_id)

        qty_delta = stmt.quantity - erp.quantity
        price_delta = stmt.unit_price - erp.po_price
        amount_delta = stmt.amount - erp.amount

        qty_ok = _within_tolerance(erp.quantity, stmt.quantity, qty_tolerance_pct)
        price_ok = _within_tolerance(erp.po_price, stmt.unit_price, price_tolerance_pct)

        if qty_ok and price_ok:
            status = "matched"
            disc_type = None
        else:
            status = "discrepancy"
            disc_type = _classify_discrepancy(qty_delta, price_delta)

        matches.append(MatchResult(
            erp=erp,
            statement=stmt,
            match_type="fuzzy",
            quantity_delta=qty_delta,
            price_delta=price_delta,
            amount_delta=amount_delta,
            status=status,
            discrepancy_type=disc_type,
            confidence=Decimal("0.90"),
            match_details={
                "layer": 2,
                "fuzzy_key": list(key),
                "original_erp_po": erp.po_number,
                "original_stmt_po": stmt.po_number,
            },
        ))

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]

    return matches, unmatched_erp, unmatched_stmt
