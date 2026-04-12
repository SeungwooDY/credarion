"""Orchestrator: read → detect header → map columns → clean → insert."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.ingestion.cleaning import clean_dataframe
from app.ingestion.column_mapping import get_cached_mapping, resolve_column_mapping
from app.ingestion.header_detection import clean_header_cells, detect_header_row
from app.models import StatementLineItem, SupplierStatement

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    status: str  # "success" | "needs_review" | "error"
    statement_id: uuid.UUID | None = None
    rows_ingested: int = 0
    rows_skipped: int = 0
    mapping_source: str | None = None
    errors: list[str] = field(default_factory=list)


def _read_file(file_path: str) -> pd.DataFrame:
    """Read an Excel or CSV file into a raw DataFrame (no header, all strings)."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=str)
    elif suffix in (".xlsx", ".xls"):
        engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
        return pd.read_excel(path, header=None, dtype=str, engine=engine)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


async def ingest_supplier_statement(
    file_path: str,
    supplier_id: uuid.UUID,
    period: str,
    db: Session,
) -> IngestionResult:
    """Full ingestion pipeline for a supplier statement file.

    Args:
        file_path: Path to the Excel/CSV file.
        supplier_id: UUID of the supplier in the database.
        period: Period string, e.g. "2026-03".
        db: SQLAlchemy session.

    Returns:
        IngestionResult with status, counts, and any errors.
    """
    result = IngestionResult(status="error")

    # Step 1: Read raw file
    try:
        df_raw = _read_file(file_path)
    except Exception as e:
        result.errors.append(f"Failed to read file: {e}")
        return result

    # Step 2: Check cached mapping first
    cached = get_cached_mapping(supplier_id, db)
    if cached:
        header_row = cached.header_row
        column_map = cached.column_map
        mapping_source = cached.source
        needs_review = False
        logger.info("Using cached %s mapping for supplier %s", mapping_source, supplier_id)
    else:
        # Step 3: Detect header row
        try:
            header_row = detect_header_row(df_raw)
        except ValueError as e:
            result.errors.append(str(e))
            return result

        # Step 4: Extract and clean headers
        raw_headers = [str(v) if pd.notna(v) else "" for v in df_raw.iloc[header_row]]
        headers = clean_header_cells(raw_headers)

        # Get sample rows for LLM (2-3 rows after header)
        sample_start = header_row + 1
        sample_end = min(sample_start + 3, len(df_raw))
        sample_rows = []
        for i in range(sample_start, sample_end):
            sample_rows.append(
                [str(v) if pd.notna(v) else "" for v in df_raw.iloc[i]]
            )

        # Step 5: Resolve column mapping (3-tier)
        column_map, mapping_source, needs_review = await resolve_column_mapping(
            headers, sample_rows, supplier_id, header_row, db
        )

    result.mapping_source = mapping_source

    if needs_review:
        result.status = "needs_review"
        result.errors.append(
            "Column mapping requires human review — could not auto-map all required fields"
        )
        db.commit()
        return result

    # Step 6: Re-read with detected header
    try:
        df = pd.read_excel(
            file_path,
            header=header_row,
            dtype=str,
            engine="openpyxl" if file_path.lower().endswith(".xlsx") else "xlrd",
        ) if not file_path.lower().endswith(".csv") else pd.read_csv(
            file_path,
            header=header_row,
            dtype=str,
        )
    except Exception as e:
        result.errors.append(f"Failed to re-read file with header: {e}")
        return result

    # Clean header names (handle multi-row headers with newlines)
    df.columns = clean_header_cells(list(df.columns.astype(str)))

    # Step 7: Clean data
    total_before = len(df)
    df = clean_dataframe(df, column_map)
    result.rows_skipped = total_before - len(df)

    # Step 8: Create SupplierStatement row
    statement = SupplierStatement(
        supplier_id=supplier_id,
        period=period,
        file_url=file_path,
    )
    db.add(statement)
    db.flush()
    result.statement_id = statement.id

    # Step 9: Bulk insert StatementLineItem rows
    line_items = []
    row_errors = 0
    for _, row in df.iterrows():
        try:
            quantity = row.get("quantity")
            unit_price = row.get("unit_price")
            amount = row.get("amount")

            # Skip rows where critical numeric fields are None
            if quantity is None and amount is None:
                row_errors += 1
                continue

            item = StatementLineItem(
                statement_id=statement.id,
                po_number=row.get("po_number"),
                material_number=row.get("material_number"),
                quantity=quantity or 0,
                unit_price=unit_price or 0,
                amount=amount or 0,
                delivery_date=row["delivery_date"].date()
                if pd.notna(row.get("delivery_date")) and row.get("delivery_date") is not None
                else None,
                delivery_note_ref=row.get("delivery_note_ref"),
                raw_row=row.get("_raw_row", {}),
            )
            line_items.append(item)
        except Exception as e:
            row_errors += 1
            logger.warning("Skipping row: %s", e)

    db.add_all(line_items)
    result.rows_ingested = len(line_items)
    result.rows_skipped += row_errors
    result.status = "success"

    db.commit()
    return result
