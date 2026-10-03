"""Re-point a mis-bound supplier statement to the correct supplier (data fix).

The statement→supplier binding is written ONCE at upload time (an FK column on
supplier_statements). A later matcher fix is forward-only: it corrects new
uploads but can't touch rows already stored under the wrong supplier. Those
rows keep reconciling against the wrong vendor's ERP receipts → 0 matches.

Re-uploading does NOT fix them: the replace/dedup path keys on
(supplier_id, period), so re-uploading under the CORRECT supplier never finds
the old row (stored under the WRONG one) and leaves it orphaned. This script
flips supplier_id in place — one row, no orphan, no duplicated line items —
then re-runs reconciliation for both the old and new supplier so the old
supplier's stale stats clear and the new one's correct results land.

Known cases (see memory supplier_binding_fix):
    沃福 (NWE202) statement mis-bound to CBZN01
    艾裕兴 (LXD202) statement mis-bound to AXK201

Dry-run by default; pass --apply to commit.

Usage (from backend/):
    # precise: identify the exact statement, name the correct supplier
    .venv/bin/python -m scripts.repoint_statement --statement <uuid> --to LXD202
    # convenience: find the statement under the wrong supplier for a period
    .venv/bin/python -m scripts.repoint_statement --from AXK201 --to LXD202 --period 2026-07
    # commit:
    .venv/bin/python -m scripts.repoint_statement --from AXK201 --to LXD202 --period 2026-07 --apply

--to / --from accept a vendor code, supplier UUID, or (partial) name.
Supplier resolution is scoped to the mis-bound statement's own org.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.db import SessionLocal
from app.models import StatementLineItem, Supplier, SupplierStatement
from app.reconciliation.orchestrator import run_reconciliation


def _find_supplier(db, needle: str, org_id: uuid.UUID) -> Supplier | None:
    """Resolve a supplier within one org by UUID, vendor code, or partial name."""
    try:
        supplier = db.get(Supplier, uuid.UUID(needle))
        return supplier if supplier and supplier.org_id == org_id else None
    except ValueError:
        pass
    q = db.query(Supplier).filter(Supplier.org_id == org_id)
    supplier = q.filter(Supplier.vendor_code == needle).first()
    if supplier:
        return supplier
    return q.filter(Supplier.name.ilike(f"%{needle}%")).first()


def _row_count(db, statement_id: uuid.UUID) -> int:
    return (
        db.query(StatementLineItem)
        .filter(StatementLineItem.statement_id == statement_id)
        .count()
    )


def _resolve_statement(db, args) -> SupplierStatement | None:
    """Locate the mis-bound statement from --statement, or --from + --period."""
    if args.statement:
        try:
            stmt = db.get(SupplierStatement, uuid.UUID(args.statement))
        except ValueError:
            print(f"ERROR: --statement {args.statement!r} is not a valid UUID", file=sys.stderr)
            return None
        if stmt is None:
            print(f"ERROR: no statement with id {args.statement}", file=sys.stderr)
        return stmt

    # convenience mode: --from supplier + --period
    # resolve the wrong supplier across all orgs (we don't know the org yet),
    # then find its statement for the period.
    try:
        wrong = db.get(Supplier, uuid.UUID(args.from_supplier))
        wrong_candidates = [wrong] if wrong else []
    except ValueError:
        wrong_candidates = (
            db.query(Supplier)
            .filter(
                (Supplier.vendor_code == args.from_supplier)
                | (Supplier.name.ilike(f"%{args.from_supplier}%"))
            )
            .all()
        )
    if not wrong_candidates:
        print(f"ERROR: no supplier matching --from {args.from_supplier!r}", file=sys.stderr)
        return None

    matches = (
        db.query(SupplierStatement)
        .filter(
            SupplierStatement.supplier_id.in_([s.id for s in wrong_candidates]),
            SupplierStatement.period == args.period,
        )
        .all()
    )
    if not matches:
        print(
            f"ERROR: no statement under {args.from_supplier!r} for period {args.period}",
            file=sys.stderr,
        )
        return None
    if len(matches) > 1:
        print(
            f"ERROR: {len(matches)} statements match; re-run with --statement <uuid>:",
            file=sys.stderr,
        )
        for m in matches:
            print(f"    {m.id}  supplier={m.supplier_id}  {m.original_filename}", file=sys.stderr)
        return None
    return matches[0]


async def _reconcile(db, supplier: Supplier, period: str) -> None:
    print(f"  recon → {supplier.vendor_code} {supplier.name} [{period}] ...", flush=True)
    run = await run_reconciliation(supplier.id, period, db)
    print(
        f"    run {run.id}: {run.status} | matched={run.matched_count} "
        f"discrepancies={run.discrepancy_count} unmatched={run.unmatched_count} "
        f"match_rate={run.auto_match_rate}%"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-point a mis-bound supplier statement.")
    parser.add_argument("--statement", help="Statement UUID (precise mode)")
    parser.add_argument(
        "--from", dest="from_supplier",
        help="Wrong supplier (vendor code/UUID/name) — with --period, convenience mode",
    )
    parser.add_argument("--to", required=True, help="Correct supplier (vendor code/UUID/name)")
    parser.add_argument("--period", help="Period, e.g. 2026-07 (required with --from)")
    parser.add_argument("--apply", action="store_true", help="Commit (default: dry-run)")
    args = parser.parse_args()

    if not args.statement and not (args.from_supplier and args.period):
        parser.error("pass --statement <uuid>, or --from <supplier> with --period")

    db = SessionLocal()
    try:
        stmt = _resolve_statement(db, args)
        if stmt is None:
            return 1

        old_supplier = db.get(Supplier, stmt.supplier_id)
        if old_supplier is None:
            print(f"ERROR: statement's current supplier {stmt.supplier_id} not found", file=sys.stderr)
            return 1

        new_supplier = _find_supplier(db, args.to, old_supplier.org_id)
        if new_supplier is None:
            print(
                f"ERROR: no supplier matching --to {args.to!r} in org {old_supplier.org_id}",
                file=sys.stderr,
            )
            return 1

        if new_supplier.id == old_supplier.id:
            print(
                f"Statement {stmt.id} is already bound to "
                f"{new_supplier.vendor_code} {new_supplier.name} — nothing to do."
            )
            return 0

        # Collision guard: if the target already has a statement for this
        # period, flipping would create the duplicate we're trying to avoid.
        clash = (
            db.query(SupplierStatement)
            .filter(
                SupplierStatement.supplier_id == new_supplier.id,
                SupplierStatement.period == stmt.period,
            )
            .first()
        )
        if clash is not None:
            print(
                f"ERROR: {new_supplier.vendor_code} already has a statement for "
                f"{stmt.period} (id {clash.id}). Resolve that first — this script "
                f"won't create a second one.",
                file=sys.stderr,
            )
            return 1

        rows = _row_count(db, stmt.id)
        verb = "Re-pointing" if args.apply else "[DRY-RUN] would re-point"
        print(f"{verb} statement {stmt.id}")
        print(f"  file:    {stmt.original_filename}")
        print(f"  period:  {stmt.period}   line items: {rows}")
        print(f"  FROM:    {old_supplier.vendor_code} {old_supplier.name}")
        print(f"  TO:      {new_supplier.vendor_code} {new_supplier.name}")

        if not args.apply:
            print("\nDry-run only. Re-run with --apply to commit and re-reconcile.")
            return 0

        stmt.supplier_id = new_supplier.id
        db.commit()
        print("  committed supplier_id update.")

        async def rerun() -> None:
            # new supplier: correct results land; old supplier: stale stats clear.
            await _reconcile(db, new_supplier, stmt.period)
            await _reconcile(db, old_supplier, stmt.period)

        asyncio.run(rerun())
        print("\nDone.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
