"""Layer 1: Exact match on (po_number, material_number) with tolerance check.

Handles duplicate PO+PN pairs in ERP by using grn_date proximity as tiebreaker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.ingestion.cleaning import normalize_po_number


@dataclass
class MatchCandidate:
    erp_id: Any
    po_number: str
    material_number: str
    quantity: Decimal
    po_price: Decimal
    amount: Decimal
    grn_date: datetime
    delivery_note: str | None = None


@dataclass
class StatementItem:
    line_id: Any
    po_number: str | None
    material_number: str | None
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    delivery_date: Any | None = None
    delivery_note_ref: str | None = None


@dataclass
class MatchResult:
    erp: MatchCandidate
    statement: StatementItem
    match_type: str
    quantity_delta: Decimal
    price_delta: Decimal
    amount_delta: Decimal
    status: str  # matched | discrepancy
    discrepancy_type: str | None = None
    confidence: Decimal = Decimal("1.0")
    match_details: dict[str, Any] = field(default_factory=dict)


def _normalize_key(po: str | None, material: str | None) -> tuple[str, str] | None:
    """Build a normalized (po, material) key. Returns None if either is missing."""
    norm_po = normalize_po_number(po)
    if norm_po is None or material is None:
        return None
    return (norm_po, material.strip())


def _classify_discrepancy(
    qty_delta: Decimal, price_delta: Decimal
) -> str | None:
    """Classify discrepancy type based on deltas (statement - ERP)."""
    if qty_delta != 0:
        return "quantity_over" if qty_delta > 0 else "quantity_under"
    if price_delta != 0:
        return "price_higher" if price_delta > 0 else "price_lower"
    return None


def _within_tolerance(
    erp_val: Decimal, stmt_val: Decimal, tolerance_pct: Decimal
) -> bool:
    """Check if two values are within tolerance percentage of the ERP value."""
    if erp_val == 0:
        return stmt_val == 0
    pct_diff = abs(stmt_val - erp_val) / abs(erp_val) * 100
    return pct_diff <= tolerance_pct


def _pick_best_erp(
    candidates: list[MatchCandidate], stmt: StatementItem
) -> MatchCandidate:
    """Pick the best ERP candidate for a statement item.

    Tiebreaker: closest grn_date to statement delivery_date,
    or matching delivery_note.
    """
    if len(candidates) == 1:
        return candidates[0]

    # Prefer delivery note match
    if stmt.delivery_note_ref:
        for c in candidates:
            if c.delivery_note and c.delivery_note.strip() == stmt.delivery_note_ref.strip():
                return c

    # Fallback: closest date
    if stmt.delivery_date is not None:
        try:
            stmt_dt = stmt.delivery_date
            if hasattr(stmt_dt, "timestamp"):
                return min(
                    candidates,
                    key=lambda c: abs((c.grn_date - stmt_dt).total_seconds()),
                )
        except (TypeError, AttributeError):
            pass

    # Default: first candidate
    return candidates[0]


def run_exact_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 1 exact matching.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    # Build ERP lookup: (po_number, material_number) → list of candidates
    erp_lookup: dict[tuple[str, str], list[MatchCandidate]] = {}
    for erp in erp_records:
        key = _normalize_key(erp.po_number, erp.material_number)
        if key is not None:
            erp_lookup.setdefault(key, []).append(erp)

    matches: list[MatchResult] = []
    unmatched_stmt: list[StatementItem] = []
    matched_erp_ids: set = set()

    for stmt in statement_items:
        key = _normalize_key(stmt.po_number, stmt.material_number)
        if key is None or key not in erp_lookup:
            unmatched_stmt.append(stmt)
            continue

        # Filter out already-matched ERP records
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
            match_type="exact",
            quantity_delta=qty_delta,
            price_delta=price_delta,
            amount_delta=amount_delta,
            status=status,
            discrepancy_type=disc_type,
            confidence=Decimal("1.0"),
            match_details={"layer": 1, "key": list(key)},
        ))

    # Unmatched ERP records
    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]

    return matches, unmatched_erp, unmatched_stmt
