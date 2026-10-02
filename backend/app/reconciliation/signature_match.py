"""Suggest-only (quantity, unit price) pairing for divergent suppliers.

Some suppliers order under the buyer's own order codes and record free-text
product names, so neither PO nor material overlaps the factory ERP — yet the
physical delivery (quantity + unit price) is identical on both sides. The
pilot case is 诚辉泰 (CHT201, paper/packaging): its statement cites GW001B…
buyer codes and names like 普通箱/啤卡, none of which appear in ERP, but ~86% of
its lines share an exact (quantity, unit_price) with an ERP receipt.

After the strict PO/material layers leave everything unmatched, this pass
surfaces (quantity, unit_price)-exact pairings as HINTS on the unmatched rows
for the accountant to confirm. Like the AI layer, it is SUGGEST-ONLY: nothing
is consumed, rows stay unmatched, the hard match rate is unchanged. Price is
compared on ERP ``po_price`` (the field the engine matches on). Date is a
tiebreaker only — it never gates a suggestion (engine rule, 2026-08-02).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.reconciliation.exact_match import (
    MatchCandidate,
    StatementItem,
    _date_gap_days,
)

logger = logging.getLogger(__name__)


def _signature(qty: Any, price: Any) -> tuple[Decimal, Decimal] | None:
    """Exact (quantity, unit_price) signature, or None if either is missing."""
    if qty is None or price is None:
        return None
    try:
        return (Decimal(str(qty)), Decimal(str(price)))
    except (ArithmeticError, ValueError):
        return None


def run_signature_suggestions(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
) -> list[dict[str, Any]]:
    """Deterministic (quantity, unit_price) pairing hints for unmatched rows.

    Returns a list of suggestion dicts, same shape as the AI layer::

        {"erp_id", "stmt_line_id", "confidence": float, "reason": str}

    Each ERP record and statement line appears in at most one suggestion (1:1);
    when a signature has several ERP candidates, the smallest delivery-date gap
    wins (date is a tiebreaker only). Nothing is consumed — callers keep every
    input row unmatched and attach these as informational hints.
    """
    erp_by_sig: dict[tuple[Decimal, Decimal], list[MatchCandidate]] = {}
    for e in erp_records:
        sig = _signature(e.quantity, e.po_price)
        if sig is not None:
            erp_by_sig.setdefault(sig, []).append(e)

    suggestions: list[dict[str, Any]] = []
    used_erp: set = set()

    for stmt in statement_items:
        sig = _signature(stmt.quantity, stmt.unit_price)
        if sig is None or sig not in erp_by_sig:
            continue
        candidates = [e for e in erp_by_sig[sig] if e.erp_id not in used_erp]
        if not candidates:
            continue
        # Date tiebreaker: smallest known gap first; unknown gaps sort last.
        def _rank(e: MatchCandidate) -> tuple[int, int]:
            gap = _date_gap_days(e, stmt)
            return (0, gap) if gap is not None else (1, 0)

        candidates.sort(key=_rank)
        erp = candidates[0]
        used_erp.add(erp.erp_id)
        # A signature shared by several ERP rows is a weaker hint than a unique
        # one, so it carries lower confidence.
        collided = len(candidates) > 1
        suggestions.append({
            "erp_id": erp.erp_id,
            "stmt_line_id": stmt.line_id,
            "confidence": 0.70 if collided else 0.85,
            "reason": (
                f"same quantity ({stmt.quantity}) and unit price "
                f"({stmt.unit_price}); PO and material differ between systems"
            ),
        })

    return suggestions
