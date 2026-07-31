"""Identical-row combining for BOTH sides of the reconciliation.

Rule (2026-07-31): quantity is the ONLY field allowed to deviate between rows
that describe the same receipt. Rows on either side are combined when PO
number, material number, per-unit price, and date are ALL identical —
quantity and amount are summed, unit price is the shared per-unit price and
is never summed.

The delivery-note ref is deliberately NOT part of the key: the supplier
statement is atomic (one line per physical delivery), so two same-day
deliveries carry different delivery notes yet the factory keys them as one
ERP receipt. Keeping the DN in the key would leave the statement side split
while the ERP side is combined, and the key join downstream would fail.

After both sides are combined, each side holds at most one row per
(PO, material, unit price, date) — matching becomes a plain key join, and
any leftover row is a real missing/extra discrepancy, never something to be
netted away by group totals.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from app.ingestion.cleaning import normalize_po_number
from app.reconciliation.exact_match import MatchCandidate, StatementItem

ZERO = Decimal("0")


class CombinedGroup:
    """Totals for one combined group, keyed by the primary (first) row."""

    __slots__ = ("line_ids", "quantity", "amount")

    def __init__(self, line_ids: list[Any], quantity: Decimal, amount: Decimal):
        self.line_ids = line_ids
        self.quantity = quantity
        self.amount = amount


def _date_key(value: Any) -> date | Any:
    """Calendar date for the combine key — time-of-day must not split groups."""
    if isinstance(value, datetime):
        return value.date()
    return value


def _identity_key(
    po: str | None, material: str | None, day: Any, price: Any
) -> tuple | None:
    """(PO, material, date, unit price) identity key. None → never combine."""
    norm_po = normalize_po_number(po)
    if norm_po is None:
        return None
    return (
        norm_po,
        (material or "").strip(),
        _date_key(day),
        # Decimal equality is value-based (1.50 == 1.5), so the per-unit
        # price participates directly.
        Decimal(str(price)) if price is not None else None,
    )


def _combine(
    items: list[Any],
    key_of: Callable[[Any], tuple | None],
    id_of: Callable[[Any], Any],
    qty_of: Callable[[Any], Decimal | None],
    amt_of: Callable[[Any], Decimal | None],
    rebuild: Callable[[Any, Decimal, Decimal], Any],
) -> tuple[list[Any], dict[Any, CombinedGroup]]:
    """Shared combining core.

    Input order preserved; each 2+ group is replaced by one row (the first
    occurrence, keeping its id) with summed quantity/amount. `groups` maps
    primary id → CombinedGroup so downstream consumers (mismatch API,
    annotated export) can fan the verdict back out to the raw rows.
    """
    by_key: dict[tuple, list[Any]] = {}
    order: list[tuple[str, Any]] = []  # ("single", item) | ("group", key)

    for item in items:
        key = key_of(item)
        if key is None:
            order.append(("single", item))
            continue
        if key not in by_key:
            by_key[key] = []
            order.append(("group", key))
        by_key[key].append(item)

    combined: list[Any] = []
    groups: dict[Any, CombinedGroup] = {}

    for kind, ref in order:
        if kind == "single":
            combined.append(ref)
            continue
        members = by_key[ref]
        primary = members[0]
        if len(members) == 1:
            combined.append(primary)
            continue
        total_qty = sum((qty_of(m) or ZERO for m in members), ZERO)
        total_amt = sum((amt_of(m) or ZERO for m in members), ZERO)
        combined.append(rebuild(primary, total_qty, total_amt))
        groups[id_of(primary)] = CombinedGroup(
            line_ids=[id_of(m) for m in members],
            quantity=total_qty,
            amount=total_amt,
        )

    return combined, groups


def combine_statement_lines(
    items: list[StatementItem],
) -> tuple[list[StatementItem], dict[Any, CombinedGroup]]:
    """Combine statement lines whose PO, material, date, and unit price all match."""
    return _combine(
        items,
        key_of=lambda s: _identity_key(
            s.po_number, s.material_number, s.delivery_date, s.unit_price
        ),
        id_of=lambda s: s.line_id,
        qty_of=lambda s: s.quantity,
        amt_of=lambda s: s.amount,
        rebuild=lambda primary, qty, amt: StatementItem(
            line_id=primary.line_id,
            po_number=primary.po_number,
            material_number=primary.material_number,
            quantity=qty,
            unit_price=primary.unit_price,
            amount=amt,
            delivery_date=primary.delivery_date,
            delivery_note_ref=primary.delivery_note_ref,
        ),
    )


def combine_erp_records(
    records: list[MatchCandidate],
) -> tuple[list[MatchCandidate], dict[Any, CombinedGroup]]:
    """Combine ERP receipts whose PO, material, date, and unit price all match.

    Handles the entry clerk forgetting to key several same-day deliveries as
    one receipt — after this, the ERP side has the same shape the statement
    side gets from `combine_statement_lines`.
    """
    return _combine(
        records,
        key_of=lambda e: _identity_key(
            e.po_number, e.material_number, e.grn_date, e.po_price
        ),
        id_of=lambda e: e.erp_id,
        qty_of=lambda e: e.quantity,
        amt_of=lambda e: e.amount,
        rebuild=lambda primary, qty, amt: MatchCandidate(
            erp_id=primary.erp_id,
            po_number=primary.po_number,
            material_number=primary.material_number,
            quantity=qty,
            po_price=primary.po_price,
            amount=amt,
            grn_date=primary.grn_date,
            delivery_note=primary.delivery_note,
        ),
    )
