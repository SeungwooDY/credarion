"""API endpoints for supplier statement ingestion and column mapping management."""
from __future__ import annotations

import re
import shutil
import tempfile
import uuid

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingestion.cleaning import normalize_po_number
from app.ingestion.column_mapping import try_alias_mapping
from app.ingestion.header_detection import clean_header_cells, detect_header_row
from app.ingestion.statement_ingestor import IngestionResult, ingest_supplier_statement
from app.models import ERPRecord, StatementLineItem, Supplier, SupplierColumnMapping, SupplierStatement

router = APIRouter(prefix="/api/v1/statements", tags=["statements"])


# --- Response schemas ---


class IngestionResponse(BaseModel):
    status: str
    statement_id: str | None = None
    rows_ingested: int = 0
    rows_skipped: int = 0
    mapping_source: str | None = None
    errors: list[str] = []


class ExistingStatementInfo(BaseModel):
    statement_id: str
    supplier_id: str
    period: str
    upload_date: str
    row_count: int


class POOverlapInfo(BaseModel):
    file_po_count: int
    erp_po_count: int
    common_po_count: int
    overlap_pct: float
    warning: str | None = None


class PreviewResponse(BaseModel):
    detected_supplier_name: str | None = None
    matched_supplier_id: str | None = None
    matched_supplier_name: str | None = None
    detected_period: str | None = None
    header_row: int
    columns: list[str]
    column_mapping: dict[str, str] | None = None
    preview_rows: list[dict[str, str]]
    total_data_rows: int
    temp_file: str
    po_overlap: POOverlapInfo | None = None


class ColumnMappingResponse(BaseModel):
    id: str
    supplier_id: str
    column_map: dict[str, str]
    source: str
    confidence: float | None = None
    header_row: int
    needs_review: bool


class ColumnMappingUpdate(BaseModel):
    column_map: dict[str, str]


# --- Endpoints ---


@router.post("/preview", response_model=PreviewResponse)
async def preview_statement(
    file: UploadFile = File(...),
    org_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
) -> PreviewResponse:
    """Preview a statement file before uploading.

    Reads the file, detects the header row, extracts supplier name from
    the top rows, attempts to match to an existing supplier, detects the
    period, and returns a preview of the first few data rows.
    """
    suffix = "." + file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        # Read raw file
        if suffix == ".csv":
            df_raw = pd.read_csv(tmp_path, header=None, dtype=str)
        else:
            engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
            df_raw = pd.read_excel(tmp_path, header=None, dtype=str, engine=engine)

        # Detect header row
        header_row = detect_header_row(df_raw)

        # Extract supplier name from rows above header
        supplier_name = _extract_supplier_name(df_raw, header_row)

        # Detect period from rows above header
        detected_period = _extract_period(df_raw, header_row)

        # Match supplier to DB
        matched_supplier = None
        if supplier_name:
            matched_supplier = _match_supplier_name(supplier_name, org_id, db)

        # Get column headers
        raw_headers = [str(v) if pd.notna(v) else "" for v in df_raw.iloc[header_row]]
        columns = clean_header_cells(raw_headers)

        # Get sample data rows for material number validation
        sample_start = header_row + 1
        sample_end = min(sample_start + 5, len(df_raw))
        sample_rows = []
        for i in range(sample_start, sample_end):
            sample_rows.append(
                [str(v) if pd.notna(v) else "" for v in df_raw.iloc[i]]
            )

        # Try column mapping
        column_mapping = try_alias_mapping(columns, sample_rows)

        # Re-read with header for preview rows
        if suffix == ".csv":
            df = pd.read_csv(tmp_path, header=header_row, dtype=str, nrows=header_row + 10)
        else:
            df = pd.read_excel(tmp_path, header=header_row, dtype=str, engine=engine)
        df.columns = clean_header_cells(list(df.columns.astype(str)))

        total_data_rows = len(df)
        preview_rows = []
        for _, row in df.head(5).iterrows():
            preview_rows.append({
                col: str(v) if pd.notna(v) else ""
                for col, v in row.items()
                if col  # skip empty column names
            })

        # Check PO overlap with ERP data if we have a matched supplier
        po_overlap = None
        if matched_supplier and column_mapping:
            po_overlap = _check_po_overlap(df, column_mapping, matched_supplier.id, db)

        return PreviewResponse(
            detected_supplier_name=supplier_name,
            matched_supplier_id=str(matched_supplier.id) if matched_supplier else None,
            matched_supplier_name=matched_supplier.name if matched_supplier else None,
            detected_period=detected_period,
            header_row=header_row,
            columns=[c for c in columns if c],
            column_mapping=column_mapping,
            preview_rows=preview_rows,
            total_data_rows=total_data_rows,
            temp_file=tmp_path,
            po_overlap=po_overlap,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")


@router.get("/check")
async def check_existing(
    supplier_id: uuid.UUID = Query(...),
    period: str = Query(...),
    db: Session = Depends(get_db),
) -> ExistingStatementInfo | None:
    """Check if a statement already exists for this supplier+period."""
    existing = _find_existing(supplier_id, period, db)
    if not existing:
        return None
    return existing


@router.post("/upload", response_model=IngestionResponse, status_code=201)
async def upload_statement(
    file: UploadFile = File(...),
    supplier_id: uuid.UUID = Form(...),
    period: str = Form(...),
    replace: bool = Form(False),
    db: Session = Depends(get_db),
) -> IngestionResponse:
    """Upload a supplier statement file for ingestion.

    Accepts .xlsx, .xls, or .csv files. Automatically detects headers,
    maps columns, cleans data, and inserts line items.

    If a statement already exists for this supplier+period:
      - Without replace=true: returns 409 Conflict with existing statement info
      - With replace=true: deletes the old statement and uploads the new one

    Returns 201 on success, 202 if column mapping needs human review.
    """
    existing = _find_existing(supplier_id, period, db)
    if existing and not replace:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A statement already exists for this supplier and period",
                "existing": existing.model_dump(),
            },
        )

    # Delete old statement if replacing
    if existing and replace:
        old_stmt = db.query(SupplierStatement).filter(
            SupplierStatement.id == uuid.UUID(existing.statement_id)
        ).first()
        if old_stmt:
            db.query(StatementLineItem).filter(
                StatementLineItem.statement_id == old_stmt.id
            ).delete()
            db.delete(old_stmt)
            db.flush()

    # Save uploaded file to a temp location
    suffix = "." + file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    result: IngestionResult = await ingest_supplier_statement(
        file_path=tmp_path,
        supplier_id=supplier_id,
        period=period,
        db=db,
        force_remap=replace,
    )

    response = IngestionResponse(
        status=result.status,
        statement_id=str(result.statement_id) if result.statement_id else None,
        rows_ingested=result.rows_ingested,
        rows_skipped=result.rows_skipped,
        mapping_source=result.mapping_source,
        errors=result.errors,
    )

    if result.status == "error":
        raise HTTPException(status_code=400, detail=response.model_dump())

    # Return 202 if needs review, 201 if success
    return response


@router.put("/mappings/{mapping_id}", response_model=ColumnMappingResponse)
async def update_mapping(
    mapping_id: uuid.UUID,
    body: ColumnMappingUpdate,
    db: Session = Depends(get_db),
) -> ColumnMappingResponse:
    """Manually confirm or update a column mapping (Tier 3 human review)."""
    mapping = (
        db.query(SupplierColumnMapping)
        .filter(SupplierColumnMapping.id == mapping_id)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    mapping.column_map = body.column_map
    mapping.source = "manual"
    mapping.needs_review = False
    mapping.confidence = None
    db.commit()
    db.refresh(mapping)

    return _mapping_to_response(mapping)


@router.get("/mappings/{supplier_id}", response_model=ColumnMappingResponse)
async def get_mapping(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ColumnMappingResponse:
    """Get the current column mapping for a supplier."""
    mapping = (
        db.query(SupplierColumnMapping)
        .filter(SupplierColumnMapping.supplier_id == supplier_id)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="No mapping found for this supplier")

    return _mapping_to_response(mapping)


def _mapping_to_response(mapping: SupplierColumnMapping) -> ColumnMappingResponse:
    return ColumnMappingResponse(
        id=str(mapping.id),
        supplier_id=str(mapping.supplier_id),
        column_map=mapping.column_map,
        source=mapping.source,
        confidence=float(mapping.confidence) if mapping.confidence is not None else None,
        header_row=mapping.header_row,
        needs_review=mapping.needs_review,
    )


def _find_existing(
    supplier_id: uuid.UUID, period: str, db: Session
) -> ExistingStatementInfo | None:
    """Check if a statement already exists for supplier+period."""
    stmt = (
        db.query(SupplierStatement)
        .filter(
            SupplierStatement.supplier_id == supplier_id,
            SupplierStatement.period == period,
        )
        .first()
    )
    if not stmt:
        return None
    row_count = (
        db.query(StatementLineItem)
        .filter(StatementLineItem.statement_id == stmt.id)
        .count()
    )
    return ExistingStatementInfo(
        statement_id=str(stmt.id),
        supplier_id=str(stmt.supplier_id),
        period=stmt.period,
        upload_date=str(stmt.upload_date) if stmt.upload_date else "",
        row_count=row_count,
    )


def _extract_supplier_name(df_raw: pd.DataFrame, header_row: int) -> str | None:
    """Extract supplier company name from rows above the header.

    Chinese company names typically end with 有限公司 or 有限责任公司.
    Also looks for patterns like 供货单位：XXX.
    """
    company_pattern = re.compile(r"[\u4e00-\u9fff]{2,}(?:有限公司|有限责任公司)")
    supply_pattern = re.compile(r"供[货貨]单位[：:]?\s*([\u4e00-\u9fff（()）\s]+(?:有限公司|有限责任公司))")
    # Also try the customer's name (购货单位) so we can exclude it
    customer_pattern = re.compile(r"[购購][货貨]单位[：:]?\s*([\u4e00-\u9fff（()）\s]+(?:有限公司|有限责任公司))")

    customer_name = None
    supplier_candidates: list[str] = []

    for idx in range(min(header_row, len(df_raw))):
        row_text = " ".join(str(v) for v in df_raw.iloc[idx] if pd.notna(v))
        row_text = row_text.replace(" ", "")

        # Check for explicit 供货单位 label
        m = supply_pattern.search(row_text)
        if m:
            return m.group(1).strip()

        # Track the customer name to exclude it
        m = customer_pattern.search(row_text)
        if m:
            customer_name = m.group(1).strip()

        # Find any company name
        for match in company_pattern.finditer(row_text):
            name = match.group(0).strip()
            # Skip very short matches or common labels
            if len(name) >= 6:
                supplier_candidates.append(name)

    # Return the first company name that isn't the customer
    for name in supplier_candidates:
        if customer_name and name == customer_name:
            continue
        return name

    return None


def _extract_period(df_raw: pd.DataFrame, header_row: int) -> str | None:
    """Extract statement period (YYYY-MM) from rows above the header.

    Looks for patterns like 2026年3月, 2026年03月, 3月份对账单 etc.
    """
    # Match: 2026年3月 or 2026年03月
    full_pattern = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月")
    # Match: just month like "3月份对账单" (less reliable, skip for now)

    for idx in range(min(header_row, len(df_raw))):
        row_text = " ".join(str(v) for v in df_raw.iloc[idx] if pd.notna(v))
        m = full_pattern.search(row_text)
        if m:
            year = m.group(1)
            month = m.group(2).zfill(2)
            return f"{year}-{month}"

    return None


def _check_po_overlap(
    df: pd.DataFrame, column_mapping: dict[str, str], supplier_id: uuid.UUID, db: Session
) -> POOverlapInfo | None:
    """Check how many PO numbers from the file match the supplier's ERP data."""
    # Find the PO column in the file
    po_col = None
    for file_col, mapped_name in column_mapping.items():
        if mapped_name == "po_number":
            po_col = file_col
            break
    if not po_col or po_col not in df.columns:
        return None

    # Extract unique normalized POs from file
    file_pos: set[str] = set()
    for val in df[po_col].dropna():
        norm = normalize_po_number(str(val))
        if norm:
            file_pos.add(norm)
    if not file_pos:
        return None

    # Get unique POs from ERP for this supplier
    erp_pos_raw = (
        db.query(ERPRecord.po_number)
        .filter(ERPRecord.supplier_id == supplier_id)
        .distinct()
        .all()
    )
    erp_pos: set[str] = set()
    for (po,) in erp_pos_raw:
        norm = normalize_po_number(po)
        if norm:
            erp_pos.add(norm)

    common = file_pos & erp_pos
    overlap_pct = (len(common) / len(file_pos) * 100) if file_pos else 0

    warning = None
    if len(common) == 0 and len(erp_pos) > 0:
        warning = (
            "None of the PO numbers in this file match this supplier's ERP data. "
            "This file may belong to a different supplier."
        )
    elif overlap_pct < 30 and len(file_pos) > 3:
        warning = (
            f"Only {len(common)} of {len(file_pos)} PO numbers match this supplier's "
            f"ERP data ({overlap_pct:.0f}%). This file may belong to a different supplier."
        )

    return POOverlapInfo(
        file_po_count=len(file_pos),
        erp_po_count=len(erp_pos),
        common_po_count=len(common),
        overlap_pct=round(overlap_pct, 1),
        warning=warning,
    )


def _match_supplier_name(name: str, org_id: uuid.UUID, db: Session) -> Supplier | None:
    """Match extracted supplier name to a supplier in the DB.

    Tries: exact match → best substring match (longest overlap wins).
    """
    # Exact match
    supplier = (
        db.query(Supplier)
        .filter(Supplier.org_id == org_id, Supplier.name == name)
        .first()
    )
    if supplier:
        return supplier

    # Substring match — pick the longest-name match to avoid false positives
    # from short names matching inside longer ones
    suppliers = db.query(Supplier).filter(Supplier.org_id == org_id).all()
    candidates: list[tuple[int, Supplier]] = []
    for s in suppliers:
        if name in s.name or s.name in name:
            # Score by how much of the extracted name overlaps with the DB name
            overlap = min(len(name), len(s.name))
            candidates.append((overlap, s))

    if not candidates:
        return None

    # Return the candidate with the longest overlap (most specific match)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
