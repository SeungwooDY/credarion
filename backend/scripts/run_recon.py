"""Run reconciliation for a supplier+period from the command line.

Reconciliation now runs automatically in the background on statement/GRN
uploads; this script is the manual trigger for engine testing and debugging
(replacing the reconciliation page as the observation point).

Usage (from backend/):
    .venv/bin/python -m scripts.run_recon --supplier 590 --period 2026-03
    .venv/bin/python -m scripts.run_recon --supplier "深圳市X有限公司" --period 2026-03
    .venv/bin/python -m scripts.run_recon --all --period 2026-03

--supplier accepts a vendor code, supplier UUID, or (partial) name.
--all runs every supplier that has a statement for the period.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.db import SessionLocal
from app.models import Supplier, SupplierStatement
from app.reconciliation.orchestrator import run_reconciliation


def _find_supplier(db, needle: str) -> Supplier | None:
    try:
        return db.get(Supplier, uuid.UUID(needle))
    except ValueError:
        pass
    supplier = db.query(Supplier).filter(Supplier.vendor_code == needle).first()
    if supplier:
        return supplier
    return db.query(Supplier).filter(Supplier.name.ilike(f"%{needle}%")).first()


async def _run(db, supplier: Supplier, period: str) -> None:
    print(f"→ {supplier.vendor_code} {supplier.name} [{period}] ...", flush=True)
    run = await run_reconciliation(supplier.id, period, db)
    print(
        f"  run {run.id}: {run.status} | matched={run.matched_count} "
        f"discrepancies={run.discrepancy_count} unmatched={run.unmatched_count} "
        f"match_rate={run.auto_match_rate}%"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reconciliation manually.")
    parser.add_argument("--supplier", help="Vendor code, UUID, or partial name")
    parser.add_argument("--period", required=True, help='Period, e.g. "2026-03"')
    parser.add_argument(
        "--all", action="store_true",
        help="Run every supplier with a statement for the period",
    )
    args = parser.parse_args()
    if not args.all and not args.supplier:
        parser.error("pass --supplier or --all")

    db = SessionLocal()
    try:
        if args.all:
            supplier_ids = [
                sid
                for (sid,) in db.query(SupplierStatement.supplier_id)
                .filter(SupplierStatement.period == args.period)
                .distinct()
            ]
            suppliers = (
                db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()
                if supplier_ids
                else []
            )
            if not suppliers:
                print(f"No suppliers with a statement for {args.period}", file=sys.stderr)
                return 1
        else:
            supplier = _find_supplier(db, args.supplier)
            if supplier is None:
                print(f"ERROR: no supplier matching {args.supplier!r}", file=sys.stderr)
                return 1
            suppliers = [supplier]

        async def run_all() -> None:
            for s in suppliers:
                await _run(db, s, args.period)

        asyncio.run(run_all())
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
