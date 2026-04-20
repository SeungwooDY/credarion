"""Pydantic schemas for invoice processing API request/response."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# --- Response schemas ---


class InvoiceLineItemDetail(BaseModel):
    id: str
    invoice_id: str
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    po_number: str | None = None
    material_number: str | None = None
    raw_fields: dict | None = None


class InvoiceDetail(BaseModel):
    id: str
    org_id: str
    supplier_id: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    subtotal: float | None = None
    vat_rate: float | None = None
    vat_amount: float | None = None
    total_amount: float | None = None
    currency: str = "RMB"
    status: str
    file_url: str
    file_type: str
    original_filename: str | None = None
    extraction_confidence: float | None = None
    field_confidences: dict | None = None
    needs_review: bool = False
    supplier_name_extracted: str | None = None
    extracted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    line_items: list[InvoiceLineItemDetail] = []


class InvoiceListItem(BaseModel):
    id: str
    invoice_number: str | None = None
    invoice_date: date | None = None
    total_amount: float | None = None
    currency: str = "RMB"
    status: str
    supplier_id: str | None = None
    supplier_name_extracted: str | None = None
    needs_review: bool = False
    extraction_confidence: float | None = None
    created_at: datetime


class InvoiceUploadResponse(BaseModel):
    invoices: list[InvoiceListItem]
    message: str = "Upload complete"


# --- Update schemas ---


class InvoiceUpdate(BaseModel):
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    subtotal: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    supplier_name_extracted: str | None = None


class InvoiceLineItemUpdate(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    po_number: str | None = None
    material_number: str | None = None


class StatusTransition(BaseModel):
    status: str = Field(..., description="Target status")


# Status transition validation
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "received": ["extracted"],
    "extracted": ["matched", "approved"],
    "matched": ["approved"],
    "approved": ["paid"],
}
