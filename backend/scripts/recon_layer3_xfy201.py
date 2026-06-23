"""READ-ONLY real-data check for Layer 3 (multi-delivery aggregation).

Runs the reconciliation waterfall up to Layer 3 against the real 丰裕达 (XFY201)
data for period 2026-03, then prints how many (po, material) groups Layer 3
formed, how many matched, and how many remained as discrepancies.

Faithful to requirement #1 ("ERP records not already matched by Layers 1 and 2"):
Layers 1 and 2 run first, with the production `_split_by_balance` pre-routing so
that multi-delivery groups survive to Layer 3 instead of being consumed 1:1 by
Layer 1. No writes / commits.

Run from backend/:  .venv/bin/python -m scripts.recon_layer3_xfy201
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.db import SessionLocal
from app.models import (
    ERPRecord,
    StatementLineItem,
    Supplier,
    SupplierStatement,
)
from app.reconciliation.exact_match import run_exact_match
from app.reconciliation.fuzzy_match import run_fuzzy_match
from app.reconciliation.multi_delivery import (
    _group_key,
    run_multi_delivery_match,
)
from app.reconciliation.orchestrator import (
    _erp_to_candidate,
    _period_date_range,
    _split_by_balance,
    _stmt_to_item,
)

PERIOD = "2026-03"
VENDOR = "XFY201"
QTY_TOL = Decimal("0.50")
PRICE_TOL = Decimal("0.50")


def main() -> None:
    db = SessionLocal()
    try:
        supplier = (
            db.query(Supplier).filter(Supplier.vendor_code == VENDOR).first()
        )
        if not supplier:
            print(f"No supplier with vendor_code={VENDOR}")
            return
        print(f"Supplier: {supplier.name} (vendor_code={VENDOR})")

        start, end = _period_date_range(PERIOD)
        erp = (
            db.query(ERPRecord)
            .filter(
                ERPRecord.supplier_id == supplier.id,
                ERPRecord.grn_date >= start,
                ERPRecord.grn_date <= end,
            )
            .all()
        )
        lines = []
        for st in (
            db.query(SupplierStatement)
            .filter(
                SupplierStatement.supplier_id == supplier.id,
                SupplierStatement.period == PERIOD,
            )
            .all()
        ):
            lines.extend(
                db.query(StatementLineItem)
                .filter(StatementLineItem.statement_id == st.id)
                .all()
            )
        print(f"Loaded {len(erp)} ERP records, {len(lines)} statement lines for {PERIOD}\n")

        erp_c = [_erp_to_candidate(r) for r in erp]
        stmt_c = [_stmt_to_item(l) for l in lines]

        # Layers 1 & 2 (with production pre-split so multi-delivery groups survive)
        bal_erp, bal_stmt, imb_erp, imb_stmt = _split_by_balance(erp_c, stmt_c)
        _, ue, us = run_exact_match(bal_erp, bal_stmt, QTY_TOL, PRICE_TOL)
        _, ue, us = run_fuzzy_match(ue, us, QTY_TOL, PRICE_TOL)

        l3_erp = imb_erp + ue
        l3_stmt = imb_stmt + us
        print(
            f"Into Layer 3: {len(l3_erp)} ERP rows, {len(l3_stmt)} statement lines "
            f"(not matched 1:1 by Layers 1 & 2)"
        )

        matches, rem_erp, rem_stmt = run_multi_delivery_match(
            l3_erp, l3_stmt, QTY_TOL, PRICE_TOL
        )

        # --- Group-level tally (one logical group per (po, material)) ---
        group_status: dict[str, str] = {}
        group_disc: dict[str, str | None] = {}
        for m in matches:
            gk = m.match_details["group_key"]
            group_status[gk] = m.status  # status is uniform within a group
            group_disc[gk] = m.discrepancy_type

        formed = len(group_status)
        matched = sum(1 for s in group_status.values() if s == "matched")
        discrepancies = sum(1 for s in group_status.values() if s == "discrepancy")

        disc_breakdown: dict[str, int] = defaultdict(int)
        for gk, s in group_status.items():
            if s == "discrepancy":
                disc_breakdown[group_disc[gk] or "unknown"] += 1

        # Leftover groups with no counterpart (orchestrator tail -> NULL side)
        erp_only_keys = {
            _group_key(e.po_number, e.material_number) for e in rem_erp
        } - {None}
        stmt_only_keys = {
            _group_key(s.po_number, s.material_number) for s in rem_stmt
        } - {None}

        print("\n================ Layer 3 (multi-delivery) results ================")
        print(f"  ERP groups formed (po+material on both sides): {formed}")
        print(f"  Matched groups (totals agree within ±0.5%):    {matched}")
        print(f"  Discrepancy groups:                            {discrepancies}")
        for dtype, n in sorted(disc_breakdown.items()):
            print(f"       - {dtype}: {n}")
        print(
            f"  Leftover ERP rows with no statement counterpart: {len(rem_erp)} "
            f"(in {len(erp_only_keys)} po+material groups) -> missing_from_statement"
        )
        print(
            f"  Leftover statement lines with no ERP counterpart: {len(rem_stmt)} "
            f"(in {len(stmt_only_keys)} po+material groups) -> missing_from_erp"
        )

        # Show a few matched groups for sanity
        print("\n  Sample matched groups:")
        shown = 0
        for gk, s in group_status.items():
            if s != "matched":
                continue
            sample = next(m for m in matches if m.match_details["group_key"] == gk)
            d = sample.match_details
            print(
                f"    {gk}: {d['erp_lines']} ERP rows (sum {d['erp_total_qty']}) "
                f"== {d['stmt_lines']} stmt lines (sum {d['stmt_total_qty']})"
            )
            shown += 1
            if shown >= 6:
                break
    finally:
        db.close()


if __name__ == "__main__":
    main()
