"""Orchestrator: read SGWERP GRN CSV → map columns → clean → upsert suppliers → insert erp_records.

The GRN file is a single-format CSV export from SGWERP (the pilot's ERP system).
Unlike supplier statements, there is no header detection or AI mapping needed —
the column names are consistent across exports. We just need a static alias map.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.cleaning import (
    normalize_numeric,
    normalize_po_number,
    parse_date,
    strip_part_number,
)
from app.models import ERPRecord, Organization, Supplier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SGWERP GRN column alias map
# ---------------------------------------------------------------------------
# Maps canonical field names → known Chinese column headers in the GRN export.
# The GRN file has 43 columns; we only extract the ones that map to erp_records.

GRN_COLUMN_ALIASES: dict[str, list[str]] = {
    "vend_no": ["供应商编码", "供应商代码", "vend_no", "供应商编号"],
    "vend_name": ["供应商名称", "供应商简称", "vend_name"],
    "po_number": ["采购订单号", "订单号", "PO号", "po_number", "采购单号", "po"],
    "material_number": ["物料编码", "物料编号", "产品编码", "material_number", "物料代码", "pn"],
    "quantity": ["收货数量", "实收数量", "验收数量", "入库数量", "quantity", "数量", "grn_accept"],
    "po_price": ["采购单价", "订单单价", "含税单价", "po_price", "单价"],
    "unit_price": ["不含税单价", "税前单价", "unit_price"],
    "amount": ["金额", "采购金额", "含税金额", "amount", "总金额", "AMOUNT"],
    "currency": ["币别", "货币", "currency", "币种", "po_cur"],
    "vat_rate": ["税率", "税率(%)", "vat_rate", "税率(%)", "po_vat"],
    "grn_number": ["收货单号", "入库单号", "grn_number", "收货单编号", "grn_no"],
    "grn_date": ["收货日期", "入库日期", "grn_date", "收货时间"],
    "delivery_order": ["送货单号", "delivery_order", "do_number"],
    "delivery_note": ["送货单", "交货单号", "delivery_note", "dn_no"],
}


@dataclass
class GRNIngestionResult:
    status: str  # "success" | "error"
    rows_ingested: int = 0
    rows_skipped: int = 0
    rows_duplicate: int = 0
    suppliers_created: int = 0
    suppliers_existing: int = 0
    errors: list[str] = field(default_factory=list)


def _resolve_grn_columns(df_columns: list[str]) -> dict[str, str]:
    """Map actual CSV column names to canonical field names.

    Returns:
        Dict mapping canonical name → actual column header found in the file.
    """
    mapping: dict[str, str] = {}
    normalised = {col.strip(): col for col in df_columns}

    for canonical, aliases in GRN_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                mapping[canonical] = normalised[alias]
                break

    return mapping


def _parse_vat_rate(val: object) -> int | None:
    """Parse VAT rate: '13', '13%', '0.13' → 13."""
    if pd.isna(val) or str(val).strip() == "":
        return None
    s = str(val).strip().rstrip("%")
    try:
        f = float(s)
        # If it looks like a decimal ratio (0.13), convert to percentage
        if 0 < f < 1:
            return int(round(f * 100))
        return int(round(f))
    except (ValueError, OverflowError):
        return None


def _parse_currency(val: object) -> str:
    """Normalise currency codes: 人民币/CNY → RMB, 美元 → USD, 港币 → HKD."""
    if pd.isna(val) or str(val).strip() == "":
        return "RMB"  # Default for domestic suppliers
    s = str(val).strip().upper()

    if s in ("RMB", "CNY", "人民币"):
        return "RMB"
    if s in ("USD", "美元", "美金"):
        return "USD"
    if s in ("HKD", "港币", "港元"):
        return "HKD"
    # Fallback: return as-is if it's a 3-letter code, else default
    if len(s) == 3 and s.isalpha():
        return s
    return "RMB"


def _upsert_suppliers(
    df: pd.DataFrame,
    col_map: dict[str, str],
    org_id: uuid.UUID,
    db: Session,
) -> dict[str, uuid.UUID]:
    """Create or fetch suppliers from unique vend_no values in the GRN data.

    Returns:
        Dict mapping vend_no → supplier UUID.
    """
    vend_col = col_map.get("vend_no")
    name_col = col_map.get("vend_name")

    if not vend_col:
        raise ValueError("GRN file missing supplier identifier column (供应商编码)")

    # Build unique vendor_code → name lookup from the data
    vendor_pairs: dict[str, str] = {}
    for _, row in df.drop_duplicates(subset=[vend_col]).iterrows():
        code = str(row[vend_col]).strip() if pd.notna(row[vend_col]) else ""
        if not code:
            continue
        name = str(row[name_col]).strip() if name_col and pd.notna(row.get(name_col)) else code
        vendor_pairs[code] = name

    # Fetch existing suppliers for this org
    existing = db.execute(
        select(Supplier).where(
            Supplier.org_id == org_id,
            Supplier.vendor_code.in_(list(vendor_pairs.keys())),
        )
    ).scalars().all()

    vendor_map: dict[str, uuid.UUID] = {s.vendor_code: s.id for s in existing}
    created = 0

    for code, name in vendor_pairs.items():
        if code not in vendor_map:
            supplier = Supplier(
                org_id=org_id,
                vendor_code=code,
                name=name,
            )
            db.add(supplier)
            db.flush()  # Get the id
            vendor_map[code] = supplier.id
            created += 1

    logger.info(
        "Suppliers: %d existing, %d created from %d unique vendor codes",
        len(existing),
        created,
        len(vendor_pairs),
    )
    return vendor_map


def ingest_grn(
    file_path: str,
    org_id: uuid.UUID,
    db: Session,
    on_progress: object = None,
) -> GRNIngestionResult:
    """Full ingestion pipeline for SGWERP GRN CSV export.

    Args:
        file_path: Path to the GRN CSV file.
        org_id: UUID of the organization.
        db: SQLAlchemy session.

    Returns:
        GRNIngestionResult with status, counts, and any errors.
    """
    result = GRNIngestionResult(status="error")
    path = Path(file_path)

    # Step 1: Read file
    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(path, dtype=str, encoding="utf-8")
        elif suffix in (".xlsx", ".xls"):
            engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
            df = pd.read_excel(path, dtype=str, engine=engine)
        else:
            result.errors.append(f"Unsupported file format: {suffix}")
            return result
    except Exception as e:
        result.errors.append(f"Failed to read file: {e}")
        return result

    total_rows = len(df)
    logger.info("Read GRN file: %d rows, %d columns", total_rows, len(df.columns))
    if on_progress:
        on_progress("reading", total_rows, total_rows, f"Read {total_rows} rows from file")

    # Step 2: Resolve column mapping
    col_map = _resolve_grn_columns(list(df.columns))
    required = ["po_number", "material_number", "quantity", "po_price", "amount", "grn_number", "grn_date"]
    missing = [f for f in required if f not in col_map]
    if missing:
        result.errors.append(
            f"Could not map required columns: {missing}. "
            f"Found mappings: {col_map}. "
            f"File columns: {list(df.columns)}"
        )
        return result

    # Step 3: Verify org exists
    org = db.get(Organization, org_id)
    if not org:
        result.errors.append(f"Organization {org_id} not found")
        return result

    # Step 4: Upsert suppliers
    if on_progress:
        on_progress("suppliers", 0, 0, "Upserting suppliers...")
    try:
        vendor_map = _upsert_suppliers(df, col_map, org_id, db)
    except ValueError as e:
        result.errors.append(str(e))
        return result

    result.suppliers_created = sum(1 for _ in vendor_map.values())  # Logged separately below
    result.suppliers_existing = 0  # Will be set from _upsert_suppliers logging
    if on_progress:
        on_progress("suppliers", len(vendor_map), len(vendor_map), f"{len(vendor_map)} suppliers ready")

    # Step 5: Load existing keys for deduplication
    existing_keys: set[tuple[str, str, str, str]] = set()
    existing_rows = db.execute(
        select(
            ERPRecord.supplier_id,
            ERPRecord.po_number,
            ERPRecord.material_number,
            ERPRecord.grn_number,
        ).where(ERPRecord.org_id == org_id)
    ).all()
    for row_key in existing_rows:
        existing_keys.add((str(row_key[0]), row_key[1], row_key[2], row_key[3]))
    if on_progress:
        on_progress("dedup", len(existing_keys), len(existing_keys),
                     f"Found {len(existing_keys)} existing records for dedup check")

    # Step 6: Build raw_row and insert erp_records
    source_file = path.name
    records: list[ERPRecord] = []
    skipped = 0
    duplicates = 0

    vend_col = col_map["vend_no"] if "vend_no" in col_map else None

    progress_interval = max(1, total_rows // 20)  # report ~20 times

    for idx, row in df.iterrows():
        if on_progress and int(idx) % progress_interval == 0:
            on_progress("ingesting", int(idx), total_rows, f"Processing row {int(idx)}/{total_rows}")
        try:
            # Build raw_row for audit
            raw_row = {col: (str(row[col]) if pd.notna(row[col]) else None) for col in df.columns}

            # Extract and normalize fields
            po = normalize_po_number(row.get(col_map["po_number"]))
            material = strip_part_number(row.get(col_map["material_number"]))
            quantity = normalize_numeric(row.get(col_map["quantity"]))
            po_price = normalize_numeric(row.get(col_map["po_price"]))
            amount = normalize_numeric(row.get(col_map["amount"]))
            grn_number = str(row.get(col_map["grn_number"], "")).strip()
            grn_date = parse_date(row.get(col_map["grn_date"]))

            # Optional fields
            unit_price = normalize_numeric(row.get(col_map.get("unit_price", ""), None))
            currency_raw = row.get(col_map["currency"]) if "currency" in col_map else None
            currency = _parse_currency(currency_raw)
            vat_rate = _parse_vat_rate(row.get(col_map["vat_rate"])) if "vat_rate" in col_map else None
            delivery_order = str(row.get(col_map.get("delivery_order", ""), "")).strip() or None
            delivery_note = str(row.get(col_map.get("delivery_note", ""), "")).strip() or None

            # Resolve supplier
            vend_code = str(row[vend_col]).strip() if vend_col and pd.notna(row.get(vend_col)) else None
            if not vend_code or vend_code not in vendor_map:
                skipped += 1
                continue

            # Validate required fields
            if not po or not material or quantity is None or po_price is None or amount is None:
                skipped += 1
                continue

            if not grn_number or grn_date is None:
                skipped += 1
                continue

            # Dedup check
            dedup_key = (str(vendor_map[vend_code]), po, material, grn_number)
            if dedup_key in existing_keys:
                duplicates += 1
                continue
            existing_keys.add(dedup_key)

            record = ERPRecord(
                org_id=org_id,
                supplier_id=vendor_map[vend_code],
                po_number=po,
                material_number=material,
                quantity=quantity,
                po_price=po_price,
                unit_price=unit_price,
                amount=amount,
                currency=currency,
                vat_rate=vat_rate,
                grn_number=grn_number,
                grn_date=grn_date.to_pydatetime() if hasattr(grn_date, "to_pydatetime") else grn_date,
                delivery_order=delivery_order,
                delivery_note=delivery_note,
                source_file=source_file,
                raw_row=raw_row,
            )
            records.append(record)

        except Exception as e:
            skipped += 1
            logger.warning("Skipping row %s: %s", idx, e)

    # Step 7: Bulk insert
    if on_progress:
        on_progress("saving", 0, len(records), f"Saving {len(records)} records to database...")
    db.add_all(records)
    result.rows_ingested = len(records)
    result.rows_skipped = skipped
    result.rows_duplicate = duplicates
    result.status = "success"

    db.commit()
    if on_progress:
        on_progress("done", len(records), len(records), "Ingestion complete")
    logger.info(
        "GRN ingestion complete: %d rows ingested, %d skipped",
        len(records),
        skipped,
    )
    return result
