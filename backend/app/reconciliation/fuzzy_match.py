"""Layer 2: Fuzzy match on normalized PO numbers.

Handles cases where PO numbers differ by leading zeros, dashes, or spaces
but represent the same order. Includes PO-only fallback for cross-system
material number mismatches.
"""
from __future__ import annotations

from decimal import Decimal

from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    _build_match,
    _pick_best_erp,
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

    Strategy: fuzzy-normalized PO+PN composite key (strips dashes, zeros,
    uppercases material numbers). Catches format differences between systems.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    # Build composite lookup
    erp_composite: dict[tuple[str, str], list[MatchCandidate]] = {}
    for erp in erp_records:
        key = _fuzzy_key(erp.po_number, erp.material_number)
        if key is not None:
            erp_composite.setdefault(key, []).append(erp)

    matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    unmatched_stmt: list[StatementItem] = []

    # --- Strict PO+PN fuzzy matching ---
    for stmt in statement_items:
        key = _fuzzy_key(stmt.po_number, stmt.material_number)
        if key is not None and key in erp_composite:
            available = [e for e in erp_composite[key] if e.erp_id not in matched_erp_ids]
            if available:
                erp = _pick_best_erp(available, stmt)
                matched_erp_ids.add(erp.erp_id)
                matches.append(_build_match(erp, stmt, "fuzzy", Decimal("0.90"),
                    {"layer": 2, "key_type": "po_pn", "fuzzy_key": list(key)},
                    qty_tolerance_pct, price_tolerance_pct))
                continue
        unmatched_stmt.append(stmt)

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]

    return matches, unmatched_erp, unmatched_stmt
