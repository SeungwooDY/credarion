"""API endpoints for supplier statement ingestion and column mapping management."""
from __future__ import annotations

import shutil
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingestion.statement_ingestor import IngestionResult, ingest_supplier_statement
from app.models import SupplierColumnMapping

router = APIRouter(prefix="/api/v1/statements", tags=["statements"])


# --- Response schemas ---


class IngestionResponse(BaseModel):
    status: str
    statement_id: str | None = None
    rows_ingested: int = 0
    rows_skipped: int = 0
    mapping_source: str | None = None
    errors: list[str] = []


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


@router.post("/upload", response_model=IngestionResponse, status_code=201)
async def upload_statement(
    file: UploadFile = File(...),
    supplier_id: uuid.UUID = Form(...),
    period: str = Form(...),
    db: Session = Depends(get_db),
) -> IngestionResponse:
    """Upload a supplier statement file for ingestion.

    Accepts .xlsx, .xls, or .csv files. Automatically detects headers,
    maps columns, cleans data, and inserts line items.

    Returns 201 on success, 202 if column mapping needs human review.
    """
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
