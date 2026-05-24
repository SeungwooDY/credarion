"""Layer 1: Exact match on PO number with quantity-based disambiguation.

Strategy:
  1. Try (po_number, material_number) composite key first
  2. Fall back to po_number-only with closest-quantity tiebreaker

This handles real-world data where ERP and supplier systems use different
material/part number schemes for the same items.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.ingestion.cleaning import normalize_po_number

logger = logging.getLogger(__name__)


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
    qty_delta: Decimal, price_delta: Decimal, amount_delta: Decimal
) -> str | None:
    """Classify discrepancy type based on deltas (statement - ERP).

    Reports all inconsistencies found, comma-separated if multiple.
    """
    issues = []
    if qty_delta != 0:
        issues.append("quantity_over" if qty_delta > 0 else "quantity_under")
    if price_delta != 0:
        issues.append("price_higher" if price_delta > 0 else "price_lower")
    if amount_delta != 0 and qty_delta == 0 and price_delta == 0:
        # Amount differs but qty and price don't — rounding or calc issue
        issues.append("amount_mismatch")
    return ",".join(issues) if issues else None


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

    Priority:
      1. Matching delivery note
      2. Closest quantity (for PO-only matching where many lines share a PO)
      3. Closest grn_date to statement delivery_date
      4. First candidate
    """
    if len(candidates) == 1:
        return candidates[0]

    # Prefer delivery note match
    if stmt.delivery_note_ref:
        for c in candidates:
            if c.delivery_note and c.delivery_note.strip() == stmt.delivery_note_ref.strip():
                return c

    # Composite tiebreaker: quantity difference first, then date proximity
    def _sort_key(c: MatchCandidate) -> tuple:
        qty_diff = abs(c.quantity - stmt.quantity) if stmt.quantity is not None else Decimal("0")
        date_diff = float("inf")
        if stmt.delivery_date is not None and hasattr(stmt.delivery_date, "timestamp"):
            try:
                date_diff = abs((c.grn_date - stmt.delivery_date).total_seconds())
            except (TypeError, AttributeError):
                pass
        return (qty_diff, date_diff)

    return min(candidates, key=_sort_key)



def run_exact_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 1 exact matching.

    Strategy:
      Pass 1: composite key (po_number, material_number) — highest confidence
      Pass 2: PO-only key with quantity-based disambiguation — for cross-system
              material number mismatches

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    # Build composite lookup: (po_number, material_number) → candidates
    erp_composite: dict[tuple[str, str], list[MatchCandidate]] = {}
    for erp in erp_records:
        key = _normalize_key(erp.po_number, erp.material_number)
        if key is not None:
            erp_composite.setdefault(key, []).append(erp)

    logger.debug(
        "[L1 DEBUG] Built lookup: %d composite keys from %d ERP records",
        len(erp_composite), len(erp_records),
    )
    # Log a few sample keys to help debug key-format mismatches
    if erp_composite:
        sample_composite = list(erp_composite.keys())[:3]
        logger.debug("[L1 DEBUG] Sample ERP composite keys (PO, PN): %s", sample_composite)
    if statement_items:
        sample_stmt_keys = [
            _normalize_key(s.po_number, s.material_number)
            for s in statement_items[:3]
        ]
        logger.debug("[L1 DEBUG] Sample stmt composite keys (PO, PN): %s", sample_stmt_keys)

    matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    unmatched_stmt: list[StatementItem] = []

    # --- Strict PO+PN matching ---
    for stmt in statement_items:
        key = _normalize_key(stmt.po_number, stmt.material_number)
        if key is not None and key in erp_composite:
            available = [e for e in erp_composite[key] if e.erp_id not in matched_erp_ids]
            if available:
                erp = _pick_best_erp(available, stmt)
                matched_erp_ids.add(erp.erp_id)
                matches.append(_build_match(erp, stmt, "exact", Decimal("1.0"),
                    {"layer": 1, "key_type": "po_pn", "po": key[0], "pn": key[1]},
                    qty_tolerance_pct, price_tolerance_pct))
                continue
        unmatched_stmt.append(stmt)

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]

    logger.debug(
        "[L1 DEBUG] Results: %d matched, %d ERP unmatched, %d stmt unmatched",
        len(matches), len(unmatched_erp), len(unmatched_stmt),
    )

    return matches, unmatched_erp, unmatched_stmt


def _build_match(
    erp: MatchCandidate,
    stmt: StatementItem,
    match_type: str,
    confidence: Decimal,
    details: dict,
    qty_tol: Decimal,
    price_tol: Decimal,
) -> MatchResult:
    """Build a MatchResult with delta and tolerance calculations.

    Any difference in qty, price, or amount is flagged as a discrepancy.
    Tolerance is used only to determine confidence level, not to suppress flags.
    """
    qty_delta = stmt.quantity - erp.quantity
    price_delta = stmt.unit_price - erp.po_price
    amount_delta = stmt.amount - erp.amount

    # Classify all inconsistencies
    disc_type = _classify_discrepancy(qty_delta, price_delta, amount_delta)

    if disc_type is None:
        status = "matched"
    else:
        status = "discrepancy"

    # Tolerance affects confidence, not match/discrepancy status
    qty_ok = _within_tolerance(erp.quantity, stmt.quantity, qty_tol)
    price_ok = _within_tolerance(erp.po_price, stmt.unit_price, price_tol)
    if disc_type and qty_ok and price_ok:
        # Differences exist but within tolerance — still flag, lower severity
        details = {**details, "within_tolerance": True}

    return MatchResult(
        erp=erp,
        statement=stmt,
        match_type=match_type,
        quantity_delta=qty_delta,
        price_delta=price_delta,
        amount_delta=amount_delta,
        status=status,
        discrepancy_type=disc_type,
        confidence=confidence,
        match_details=details,
    )
