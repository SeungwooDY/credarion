"""Statement-side pre-aggregation.

The factory's ERP-entry person sometimes combines several supplier statement
lines into one ERP receipt. To mirror that, duplicate statement lines are
combined into a single line BEFORE matching — but only under the strictest
rule (accountant guidance, 2026-07): every identifying column must be
identical — same PO number, same product/material number, same delivery
date, same delivery note ref, and same per-unit price. If the PO or the
date (or anything else) differs, the lines stay separate.

Quantity and amount are summed across the combined lines; unit_price is the
shared per-unit price and is never summed — the amount check works off the
per-unit price times combined quantity, not an aggregate of aggregates.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.ingestion.cleaning import normalize_po_number
from app.reconciliation.exact_match import StatementItem


class CombinedGroup:
    """Totals for one combined group, keyed by the primary (first) line."""

    __slots__ = ("line_ids", "quantity", "amount")

    def __init__(self, line_ids: list[Any], quantity: Decimal, amount: Decimal):
        self.line_ids = line_ids
        self.quantity = quantity
        self.amount = amount


def _combine_key(item: StatementItem) -> tuple | None:
    """Identity key for combining. None → never combine this line."""
    po = normalize_po_number(item.po_number)
    if po is None:
        return None
    return (
        po,
        (item.material_number or "").strip(),
        item.delivery_date,
        # Decimal equality is value-based (1.50 == 1.5), so the per-unit
        # price participates directly.
        Decimal(str(item.unit_price)) if item.unit_price is not None else None,
        (item.delivery_note_ref or "").strip(),
    )


def combine_statement_lines(
    items: list[StatementItem],
) -> tuple[list[StatementItem], dict[Any, CombinedGroup]]:
    """Combine statement lines whose identifying columns are ALL identical.

    Returns (combined_items, groups):
      - combined_items: input order preserved; each group is replaced by one
        line (the first occurrence, keeping its line_id) with summed
        quantity/amount and the shared per-unit price.
      - groups: primary line_id → CombinedGroup, only for groups of 2+ lines,
        so downstream consumers (mismatch API, annotated export) can fan the
        group verdict back out to the raw supplier rows.
    """
    by_key: dict[tuple, list[StatementItem]] = {}
    order: list[tuple[str, Any]] = []  # ("single", item) | ("group", key)

    for item in items:
        key = _combine_key(item)
        if key is None:
            order.append(("single", item))
            continue
        if key not in by_key:
            by_key[key] = []
            order.append(("group", key))
        by_key[key].append(item)

    combined: list[StatementItem] = []
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
        total_qty = sum((m.quantity or Decimal("0") for m in members), Decimal("0"))
        total_amt = sum((m.amount or Decimal("0") for m in members), Decimal("0"))
        combined.append(
            StatementItem(
                line_id=primary.line_id,
                po_number=primary.po_number,
                material_number=primary.material_number,
                quantity=total_qty,
                unit_price=primary.unit_price,
                amount=total_amt,
                delivery_date=primary.delivery_date,
                delivery_note_ref=primary.delivery_note_ref,
            )
        )
        groups[primary.line_id] = CombinedGroup(
            line_ids=[m.line_id for m in members],
            quantity=total_qty,
            amount=total_amt,
        )

    return combined, groups
