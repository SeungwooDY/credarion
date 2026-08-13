"""Layer 1: Strict 1:1 matching on (PO, material, unit price).

Semantics (2026-08-02): quantity is the ONLY field allowed to deviate between
a paired ERP receipt and statement line. PO number, material number, and unit
price must be identical. Date is NOT a match criterion — the two systems
record the same receipt on different dates (statement vs GRN posting), so a
date gap never blocks a pair. Date is used only to rank otherwise-equal
candidates (closest date wins) and, upstream, to combine same-day rows before
matching (see preaggregate.py).

Both sides are pre-combined by identical (PO, material, price, date) before
this layer runs, so matching here is a plain key join:

  Pass A — identical unit price → matched
           (a quantity gap becomes a quantity discrepancy on the pair)
  Pass B — unit price differs → paired as a price discrepancy so the
           accountant sees both sides together

Anything left after both passes is genuinely unmatched.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from app.ingestion.cleaning import normalize_po_number

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


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
    # Either side may be None for unmatched tail rows recorded by the
    # orchestrator. Matching layers (exact/fuzzy) always populate both sides.
    erp: MatchCandidate | None
    statement: StatementItem | None
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


def _classify_discrepancy(qty_delta: Decimal, price_delta: Decimal) -> str | None:
    """Classify discrepancy type based on deltas (statement - ERP).

    Matching is decided on quantity and UNIT PRICE only — line totals are
    derived numbers that the two systems round differently, so an amount gap
    with equal qty and unit price is never a discrepancy.
    Reports all inconsistencies found, comma-separated if multiple.
    """
    issues = []
    if qty_delta != 0:
        issues.append("quantity_over" if qty_delta > 0 else "quantity_under")
    if price_delta != 0:
        issues.append("price_higher" if price_delta > 0 else "price_lower")
    return ",".join(issues) if issues else None


def _within_tolerance(
    erp_val: Decimal, stmt_val: Decimal, tolerance_pct: Decimal
) -> bool:
    """Check if two values are within tolerance percentage of the ERP value."""
    if erp_val == 0:
        return stmt_val == 0
    pct_diff = abs(stmt_val - erp_val) / abs(erp_val) * 100
    return pct_diff <= tolerance_pct


def _date_gap_days(erp: MatchCandidate, stmt: StatementItem) -> int | None:
    """Whole-day gap between grn_date and delivery_date; None if unknowable."""
    grn, dd = erp.grn_date, stmt.delivery_date
    if grn is None or dd is None:
        return None
    g = grn.date() if isinstance(grn, datetime) else grn
    d = dd.date() if isinstance(dd, datetime) else dd
    if not isinstance(g, date) or not isinstance(d, date):
        return None
    return abs((g - d).days)


def _price_equal(erp: MatchCandidate, stmt: StatementItem) -> bool:
    if erp.po_price is None or stmt.unit_price is None:
        return erp.po_price is None and stmt.unit_price is None
    return Decimal(str(stmt.unit_price)) == Decimal(str(erp.po_price))


def run_keyed_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    key_fn: Callable[[str | None, str | None], tuple | None],
    match_type: str,
    confidence: Decimal,
    layer: Any,
    qty_tolerance_pct: Decimal,
    price_tolerance_pct: Decimal,
    date_tolerance_days: int = 3,
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Strict keyed 1:1 matching, shared by the exact and fuzzy layers.

    A statement line may pair with any ERP receipt whose (PO, material) key
    matches. Date never blocks a pair (date_tolerance_days is retained for
    config compatibility but no longer filters candidates); it only ranks
    them. Passes, in order — each exists so a worse pairing can never steal
    a better pairing's counterpart (XFY201 2026-08-12: a 7,488 claim grabbed
    the 9,984 receipt that another group matched exactly, turning one real
    missing-from-ERP into a phantom qty-under plus a phantom missing row):
      A0: identical price AND quantity within tolerance — the clean pairs.
      A1: identical price, quantity deviates — qty discrepancies.
      B:  price differs — price discrepancies.
    Candidate preference within a pass: matching delivery note, then
    smallest known date gap, then closest quantity.

    Returns (matches, unmatched_erp, unmatched_statement).
    """
    erp_by_key: dict[tuple, list[MatchCandidate]] = {}
    for erp in erp_records:
        key = key_fn(erp.po_number, erp.material_number)
        if key is not None:
            erp_by_key.setdefault(key, []).append(erp)

    matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    paired_stmt_ids: set = set()

    def _qty_clean(e: MatchCandidate, stmt: StatementItem) -> bool:
        return _within_tolerance(
            e.quantity or ZERO, stmt.quantity or ZERO, qty_tolerance_pct
        )

    def _candidates(
        stmt: StatementItem, require_price: bool, require_qty: bool = False
    ) -> list[tuple[MatchCandidate, int | None]]:
        key = key_fn(stmt.po_number, stmt.material_number)
        if key is None or key not in erp_by_key:
            return []
        out = []
        for e in erp_by_key[key]:
            if e.erp_id in matched_erp_ids:
                continue
            if require_price and not _price_equal(e, stmt):
                continue
            if require_qty and not _qty_clean(e, stmt):
                continue
            out.append((e, _date_gap_days(e, stmt)))
        return out

    def _pick(
        cands: list[tuple[MatchCandidate, int | None]], stmt: StatementItem
    ) -> tuple[MatchCandidate, int | None]:
        def sort_key(pair: tuple[MatchCandidate, int | None]) -> tuple:
            e, gap = pair
            dn_match = 0 if (
                stmt.delivery_note_ref
                and e.delivery_note
                and e.delivery_note.strip() == stmt.delivery_note_ref.strip()
            ) else 1
            gap_known = 0 if gap is not None else 1
            qty_diff = abs((e.quantity or ZERO) - (stmt.quantity or ZERO))
            return (dn_match, gap_known, gap if gap is not None else 0, qty_diff)

        return min(cands, key=sort_key)

    def _run_pass(
        require_price: bool, pass_name: str, require_qty: bool = False
    ) -> None:
        for stmt in statement_items:
            if stmt.line_id in paired_stmt_ids:
                continue
            cands = _candidates(stmt, require_price, require_qty)
            if not cands:
                continue
            erp, gap = _pick(cands, stmt)
            matched_erp_ids.add(erp.erp_id)
            paired_stmt_ids.add(stmt.line_id)
            details: dict[str, Any] = {
                "layer": layer,
                "key_type": "po_pn",
                "pass": pass_name,
            }
            if gap is not None:
                details["date_gap_days"] = gap
            matches.append(_build_match(
                erp, stmt, match_type, confidence, details,
                qty_tolerance_pct, price_tolerance_pct,
            ))

    # Pass A0: identical price AND clean quantity — exact pairs claim their
    # counterparts before any qty-deviating line can steal one.
    _run_pass(require_price=True, pass_name="qty_price_exact", require_qty=True)
    # Pass A1: identical unit price, quantity deviates — qty discrepancies.
    _run_pass(require_price=True, pass_name="price_exact")
    # Pass B runs only after every line has had a chance at an exact-price
    # pair, so a price-mismatched line can never steal another line's clean
    # counterpart.
    _run_pass(require_price=False, pass_name="price_mismatch")

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]
    unmatched_stmt = [s for s in statement_items if s.line_id not in paired_stmt_ids]

    return matches, unmatched_erp, unmatched_stmt


def run_exact_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
    date_tolerance_days: int = 3,
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 1 strict matching on the normalized (PO, material) key.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    return run_keyed_match(
        erp_records,
        statement_items,
        key_fn=_normalize_key,
        match_type="exact",
        confidence=Decimal("1.0"),
        layer=1,
        qty_tolerance_pct=qty_tolerance_pct,
        price_tolerance_pct=price_tolerance_pct,
        date_tolerance_days=date_tolerance_days,
    )


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

    Any difference in qty or unit price is flagged as a discrepancy.
    Tolerance is used only to determine confidence level, not to suppress flags.
    """
    qty_delta = stmt.quantity - erp.quantity
    price_delta = stmt.unit_price - erp.po_price
    # amount_delta is informational only (money-at-risk sums) — it never
    # drives match/discrepancy status; the engine matches on qty + unit price.
    amount_delta = stmt.amount - erp.amount

    # Classify all inconsistencies
    disc_type = _classify_discrepancy(qty_delta, price_delta)

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
