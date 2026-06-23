"""Layer 3: Multi-delivery aggregation matching.

The ERP logs one row every time goods physically arrive at the warehouse, so the
same part number on the same PO can produce several ERP rows in a single month
(one per delivery day). The supplier statement, by contrast, often combines those
deliveries into one line — or splits them differently from the ERP.

Layer 3 reconciles that shape by grouping BOTH sides by (po_number, material_number),
summing the quantities (and amounts), and comparing the totals within the same
±0.5% tolerance used by Layers 1 and 2. PO numbers are normalised with the same
helper Layers 1 and 2 use (`normalize_po_number`: floats → int → string, whitespace
stripped, PO revision suffixes dropped).

Status is decided once at the group level:
  - quantity total AND amount total within tolerance → "matched"
  - quantity off            → "discrepancy" (quantity_over / quantity_under)
  - quantity ok, amount off → "discrepancy" (price_higher / price_lower)

Special case — price drift across deliveries: if the grouped ERP rows do not all
share the same `po_price`, summing them would hide a real pricing problem, so the
group is NOT treated as a clean aggregate. It is written out as a discrepancy with
resolution_note="price inconsistency across deliveries", while still carrying the
real aggregate quantity/amount deltas so a simultaneous over/under-claim is visible.

Every ERP row and every statement line in a grouped (po, material) is emitted in at
least one result, so nothing is silently dropped. Groups that exist on only one side
are returned as unmatched, so the downstream layer (AI) and the orchestrator's tail
record them with the missing side set to NULL.
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

CONFIDENCE = Decimal("0.80")
PRICE_INCONSISTENT_NOTE = "price inconsistency across deliveries"


def _group_key(po: object, material: object) -> tuple[str, str] | None:
    """Normalised (po_number, material_number) grouping key.

    Reuses Layer 1/2's `normalize_po_number` for the PO side (cast float → int →
    string, strip whitespace). Material is stripped, mirroring Layer 1's exact key.
    Returns None when either component is missing, so unkeyable rows fall through.
    """
    norm_po = normalize_po_number(po)
    if norm_po is None or material is None:
        return None
    mat = str(material).strip()
    if not mat:
        return None
    return (norm_po, mat)


def _num(value) -> Decimal:
    return value if value is not None else Decimal("0")


def _avg_price(total_amount: Decimal, total_qty: Decimal) -> Decimal:
    return total_amount / total_qty if total_qty else Decimal("0")


def _classify_group(
    erp_group: list[MatchCandidate],
    stmt_group: list[StatementItem],
    qty_tolerance_pct: Decimal,
    price_tolerance_pct: Decimal,
) -> tuple[str, str | None, str | None, Decimal, Decimal, Decimal]:
    """Decide the group verdict and its aggregate deltas.

    Returns (status, discrepancy_type, resolution_note, qty_delta, price_delta,
    amount_delta). Deltas are statement_total - erp_total, so positive = supplier
    claims more than the ERP recorded.
    """
    erp_qty = sum((_num(e.quantity) for e in erp_group), Decimal("0"))
    stmt_qty = sum((_num(s.quantity) for s in stmt_group), Decimal("0"))
    erp_amt = sum((_num(e.amount) for e in erp_group), Decimal("0"))
    stmt_amt = sum((_num(s.amount) for s in stmt_group), Decimal("0"))

    qty_delta = stmt_qty - erp_qty
    amount_delta = stmt_amt - erp_amt
    price_delta = _avg_price(stmt_amt, stmt_qty) - _avg_price(erp_amt, erp_qty)

    qty_ok = _within_tolerance(erp_qty, stmt_qty, qty_tolerance_pct)
    amount_ok = _within_tolerance(erp_amt, stmt_amt, price_tolerance_pct)
    prices_inconsistent = len({e.po_price for e in erp_group}) > 1

    if prices_inconsistent:
        # Deliveries priced differently — don't trust the aggregate as a match,
        # but still surface any real quantity/amount gap alongside the price note.
        return "discrepancy", "price_inconsistent", PRICE_INCONSISTENT_NOTE, \
            qty_delta, price_delta, amount_delta

    if qty_ok and amount_ok:
        return "matched", None, None, qty_delta, price_delta, amount_delta

    if not qty_ok:
        disc_type = "quantity_over" if qty_delta > 0 else "quantity_under"
    else:
        disc_type = "price_higher" if amount_delta > 0 else "price_lower"
    return "discrepancy", disc_type, None, qty_delta, price_delta, amount_delta


def _emit_group(
    erp_group: list[MatchCandidate],
    stmt_group: list[StatementItem],
    key: tuple[str, str],
    qty_tolerance_pct: Decimal,
    price_tolerance_pct: Decimal,
) -> list[MatchResult]:
    """Aggregate one (po, material) group and emit loss-free per-row results.

    Pairs each ERP row to its closest-quantity statement line for traceability,
    then attaches any leftover statement lines to the first ERP row — so every
    ERP row and every statement line appears in at least one MatchResult.
    """
    status, disc_type, resolution_note, qty_delta, price_delta, amount_delta = (
        _classify_group(erp_group, stmt_group, qty_tolerance_pct, price_tolerance_pct)
    )

    erp_total_qty = sum((_num(e.quantity) for e in erp_group), Decimal("0"))
    stmt_total_qty = sum((_num(s.quantity) for s in stmt_group), Decimal("0"))
    erp_total_amt = sum((_num(e.amount) for e in erp_group), Decimal("0"))
    stmt_total_amt = sum((_num(s.amount) for s in stmt_group), Decimal("0"))

    details = {
        "layer": 3,
        "match_type": "multi_delivery",
        "group_key": f"{key[0]}|{key[1]}",
        "po_number": key[0],
        "material_number": key[1],
        "erp_lines": len(erp_group),
        "stmt_lines": len(stmt_group),
        "erp_total_qty": str(erp_total_qty),
        "stmt_total_qty": str(stmt_total_qty),
        "erp_total_amt": str(erp_total_amt),
        "stmt_total_amt": str(stmt_total_amt),
    }
    if resolution_note is not None:
        details["resolution_note"] = resolution_note
        details["reason"] = "price_inconsistent"
        details["distinct_po_prices"] = sorted({str(e.po_price) for e in erp_group})

    def _result(erp: MatchCandidate, stmt: StatementItem, extra: dict | None = None) -> MatchResult:
        return MatchResult(
            erp=erp,
            statement=stmt,
            match_type="multi_delivery",
            quantity_delta=qty_delta,
            price_delta=price_delta,
            amount_delta=amount_delta,
            status=status,
            discrepancy_type=disc_type,
            confidence=CONFIDENCE,
            match_details={**details, **(extra or {})},
        )

    matches: list[MatchResult] = []
    remaining = list(stmt_group)
    for erp in erp_group:
        if remaining:
            idx = min(range(len(remaining)), key=lambda i: abs(remaining[i].quantity - erp.quantity))
            stmt = remaining.pop(idx)
        else:
            stmt = stmt_group[0]
        matches.append(_result(erp, stmt))
    for stmt in remaining:
        matches.append(_result(erp_group[0], stmt, {"note": "extra_statement_line"}))
    return matches


def run_multi_delivery_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 3 multi-delivery aggregation on items left over from Layers 1 & 2.

    Groups ERP and statement rows by normalised (po_number, material_number), sums
    each side, and compares quantity and amount totals within tolerance. ERP groups
    whose po_price is not consistent are flagged with a price-inconsistency note
    instead of being trusted as a clean aggregate.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    erp_by_key: dict[tuple[str, str], list[MatchCandidate]] = defaultdict(list)
    for e in erp_records:
        key = _group_key(e.po_number, e.material_number)
        if key is not None:
            erp_by_key[key].append(e)

    stmt_by_key: dict[tuple[str, str], list[StatementItem]] = defaultdict(list)
    for s in statement_items:
        key = _group_key(s.po_number, s.material_number)
        if key is not None:
            stmt_by_key[key].append(s)

    matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    matched_stmt_ids: set = set()

    # Only (po, material) groups present on BOTH sides can be aggregated. Groups
    # on a single side are left unmatched for Layer 4 / the orchestrator tail.
    for key in set(erp_by_key) & set(stmt_by_key):
        group = _emit_group(
            erp_by_key[key], stmt_by_key[key], key, qty_tolerance_pct, price_tolerance_pct
        )
        matches.extend(group)
        # Consume exactly what was emitted, so nothing is marked matched without a
        # corresponding result row (and nothing is silently dropped).
        for m in group:
            matched_erp_ids.add(m.erp.erp_id)
            matched_stmt_ids.add(m.statement.line_id)

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]
    unmatched_stmt = [s for s in statement_items if s.line_id not in matched_stmt_ids]

    return matches, unmatched_erp, unmatched_stmt
