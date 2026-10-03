"""List supplier statements and flag duplicate (supplier, period) uploads.

A statement is bound to a supplier+period, but nothing enforces one statement
per (supplier, period) — re-uploading under a different filename, or uploading
the same file twice, silently creates parallel rows that double-count in any
rollup and produce competing reconciliation runs. This read-only script
surfaces every statement and loudly flags any (supplier, period) with >1.

Usage (from backend/):
    .venv/bin/python -m scripts.list_statements
    .venv/bin/python -m scripts.list_statements --period 2026-08
    .venv/bin/python -m scripts.list_statements --dupes-only
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from app.db import SessionLocal
from app.models import Supplier, SupplierStatement, StatementLineItem


def main() -> int:
    parser = argparse.ArgumentParser(description="List statements; flag duplicate (supplier, period).")
    parser.add_argument("--period", help="Restrict to one period, e.g. 2026-08")
    parser.add_argument(
        "--dupes-only", action="store_true",
        help="Print only the duplicate (supplier, period) groups",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(SupplierStatement)
        if args.period:
            q = q.filter(SupplierStatement.period == args.period)
        stmts = q.order_by(SupplierStatement.period).all()

        if not stmts:
            print("No statements found.")
            return 0

        # group by (supplier_id, period) to detect duplicates
        groups: dict[tuple, list] = defaultdict(list)
        for st in stmts:
            groups[(st.supplier_id, st.period)].append(st)

        def _line(st) -> str:
            s = db.get(Supplier, st.supplier_id)
            rows = (
                db.query(StatementLineItem)
                .filter(StatementLineItem.statement_id == st.id)
                .count()
            )
            code = s.vendor_code if s else "?"
            name = s.name if s else "?"
            return f"{st.period}  {code:10}  rows={rows:<4}  {name}  [{st.original_filename}]  id={st.id}"

        if not args.dupes_only:
            for st in stmts:
                print(_line(st))

        dupes = {k: v for k, v in groups.items() if len(v) > 1}
        print(f"\n---- duplicate (supplier, period) groups: {len(dupes)} ----")
        if not dupes:
            print("None. Every (supplier, period) has exactly one statement.")
        for (supplier_id, period), members in dupes.items():
            s = db.get(Supplier, supplier_id)
            code = s.vendor_code if s else "?"
            name = s.name if s else "?"
            print(f"\n  ⚠️  {code} {name} [{period}] — {len(members)} statements:")
            for st in members:
                rows = (
                    db.query(StatementLineItem)
                    .filter(StatementLineItem.statement_id == st.id)
                    .count()
                )
                print(f"        id={st.id}  rows={rows}  uploaded={st.upload_date}  [{st.original_filename}]")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
