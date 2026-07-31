"""Layer 2: Fuzzy match on normalized PO numbers.

Handles cases where PO or material numbers differ by leading zeros, dashes,
or spaces but represent the same order. Pairing semantics are identical to
Layer 1 (strict date window, identical-price pass first) — only the key
normalization is looser.
"""
from __future__ import annotations

from decimal import Decimal

from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    run_keyed_match,
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
    date_tolerance_days: int = 3,
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 2 fuzzy matching on unmatched items from Layer 1.

    Strategy: fuzzy-normalized PO+PN composite key (strips dashes, zeros,
    uppercases material numbers). Catches format differences between systems.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    return run_keyed_match(
        erp_records,
        statement_items,
        key_fn=_fuzzy_key,
        match_type="fuzzy",
        confidence=Decimal("0.90"),
        layer=2,
        qty_tolerance_pct=qty_tolerance_pct,
        price_tolerance_pct=price_tolerance_pct,
        date_tolerance_days=date_tolerance_days,
    )
