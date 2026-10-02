"""Offline diagnosis of the engine zero-match issue (AXK201, July).

Reproduces exactly what the matching engine sees, WITHOUT touching the DB, by
reusing the real ingestion code paths:

  ERP  side: pandas read (headers row 0) + GRN_COLUMN_ALIASES  (grn_ingestor)
  Stmt side: header detection + alias column mapping + cleaning (statement_ingestor)

Then it reports WHY the strict (normalized PO, material) key fails to overlap:
  - distinct PO sets on each side + their intersection
  - distinct material sets on each side + their intersection
  - combined-key overlap (what Layer 1 actually joins on)
  - fuzzy-normalized key overlap (what Layer 2 would catch)
  - price-column availability (po_price on ERP, unit_price on stmt)

Usage (from backend/):
    .venv/bin/python -m scripts.analyze_zero_match \
        --erp ../data/samples/zero_match/july/ERP7月.xlsx \
        --stmt "../data/samples/zero_match/july/119艾裕兴2026年07月对账单（333-07）.xls" \
        --vendor AXK201
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from app.ingestion.cleaning import (
    clean_dataframe,
    normalize_po_number,
    strip_part_number,
)
from app.ingestion.column_mapping import try_alias_mapping, _REVERSE_ALIAS
from app.ingestion.grn_ingestor import GRN_COLUMN_ALIASES, _resolve_grn_columns
from app.ingestion.header_detection import clean_header_cells, detect_header_row
from app.reconciliation.normalization import (
    normalize_material_for_matching,
    normalize_po_for_matching,
)


def _read_excel(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, dtype=str, header=None)
    engine = "xlrd" if path.lower().endswith(".xls") else "openpyxl"
    return pd.read_excel(path, dtype=str, engine=engine, header=None)


def load_erp(path: str, vendor: str) -> pd.DataFrame:
    """ERP: headers in row 0, map via GRN aliases, filter to one vendor_code."""
    raw = _read_excel(path)
    # ERP files have clean headers on row 0 (grn_ingestor uses header=0).
    raw.columns = clean_header_cells(list(raw.iloc[0]))
    df = raw.iloc[1:].reset_index(drop=True)
    col_map = _resolve_grn_columns(list(df.columns))
    print(f"[ERP] resolved columns: {col_map}")
    vend_col = col_map.get("vend_no")
    if not vend_col:
        sys.exit(f"[ERP] no vendor column found; headers={list(df.columns)}")
    df = df[df[vend_col].astype(str).str.strip() == vendor].reset_index(drop=True)
    print(f"[ERP] rows for {vendor}: {len(df)}")
    out = pd.DataFrame({
        "po": df[col_map["po_number"]].apply(normalize_po_number),
        "material": df[col_map["material_number"]].apply(strip_part_number),
        "po_price": df.get(col_map.get("po_price", ""), pd.Series(dtype=str)),
        "unit_price": df.get(col_map.get("unit_price", ""), pd.Series(dtype=str)),
    })
    return out


def load_statement(path: str) -> pd.DataFrame:
    raw = _read_excel(path)  # header=None
    hdr = detect_header_row(raw)
    raw_headers = [str(v) if pd.notna(v) else "" for v in raw.iloc[hdr]]
    headers = clean_header_cells(raw_headers)
    sample = [
        [str(v) if pd.notna(v) else "" for v in raw.iloc[i]]
        for i in range(hdr + 1, min(hdr + 4, len(raw)))
    ]
    col_map = try_alias_mapping(headers, sample)
    print(f"[STMT] detected header row {hdr}: {headers}")
    print(f"[STMT] alias column map: {col_map}")
    if not col_map:
        print(f"[STMT] alias mapping FAILED (would fall to LLM/manual). "
              f"reverse-alias hits: "
              f"{[h for h in headers if h in _REVERSE_ALIAS]}")
        sys.exit(1)
    # Re-read with the detected header row so pandas dedupes empty/duplicate
    # column names, exactly as statement_ingestor Step 6 does.
    if path.lower().endswith(".csv"):
        body = pd.read_csv(path, header=hdr, dtype=str)
    else:
        engine = "xlrd" if path.lower().endswith(".xls") else "openpyxl"
        body = pd.read_excel(path, header=hdr, dtype=str, engine=engine)
    body.columns = clean_header_cells(list(body.columns.astype(str)))
    cleaned = clean_dataframe(body, col_map)
    out = pd.DataFrame({
        "po": cleaned.get("po_number"),
        "material": cleaned.get("material_number"),
        "unit_price": cleaned.get("unit_price"),
    })
    print(f"[STMT] rows: {len(out)}")
    return out


def _dump_set(label: str, vals: set) -> None:
    sample = list(sorted(v for v in vals if v))[:15]
    print(f"  {label}: {len(vals)} distinct | sample={sample}")


def report(erp: pd.DataFrame, stmt: pd.DataFrame) -> None:
    print("\n=== KEY OVERLAP DIAGNOSIS ===")
    erp_po = set(erp["po"].dropna())
    stmt_po = set(stmt["po"].dropna())
    _dump_set("ERP  PO (strict)", erp_po)
    _dump_set("STMT PO (strict)", stmt_po)
    print(f"  >> PO intersection (strict): {len(erp_po & stmt_po)}")

    erp_mat = set(erp["material"].dropna())
    stmt_mat = set(stmt["material"].dropna())
    _dump_set("ERP  material", erp_mat)
    _dump_set("STMT material", stmt_mat)
    print(f"  >> material intersection: {len(erp_mat & stmt_mat)}")

    def _key(r):
        if not (pd.notna(r.po) and pd.notna(r.material)):
            return None
        return (normalize_po_number(r.po), str(r.material).strip())

    erp_key = {k for r in erp.itertuples() if (k := _key(r))}
    stmt_key = {k for r in stmt.itertuples() if (k := _key(r))}
    print(f"\n  Layer-1 (PO,material) keys — ERP={len(erp_key)} STMT={len(stmt_key)} "
          f"intersection={len(erp_key & stmt_key)}")

    def _fkey(r):
        if not (pd.notna(r.po) and pd.notna(r.material)):
            return None
        return (normalize_po_for_matching(r.po),
                normalize_material_for_matching(r.material))

    erp_fk = {k for r in erp.itertuples() if (k := _fkey(r))}
    stmt_fk = {k for r in stmt.itertuples() if (k := _fkey(r))}
    print(f"  Layer-2 fuzzy keys    — ERP={len(erp_fk)} STMT={len(stmt_fk)} "
          f"intersection={len(erp_fk & stmt_fk)}")

    # Price availability (engine matches on ERP po_price vs STMT unit_price)
    erp_price_present = erp["po_price"].notna().sum() if "po_price" in erp else 0
    stmt_price_present = stmt["unit_price"].notna().sum() if "unit_price" in stmt else 0
    print(f"\n  ERP po_price present: {erp_price_present}/{len(erp)} | "
          f"STMT unit_price present: {stmt_price_present}/{len(stmt)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--erp", required=True)
    ap.add_argument("--stmt", required=True)
    ap.add_argument("--vendor", required=True)
    args = ap.parse_args()
    erp = load_erp(args.erp, args.vendor)
    stmt = load_statement(args.stmt)
    report(erp, stmt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
