"""Invoice processing API endpoints."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.invoicing.file_storage import get_file_path, save_upload
from app.invoicing.ocr_extractor import extract_invoice
from app.invoicing.schemas import (
    ALLOWED_TRANSITIONS,
    InvoiceDetail,
    InvoiceLineItemDetail,
    InvoiceLineItemUpdate,
    InvoiceListItem,
    InvoiceUpdate,
    InvoiceUploadResponse,
    StatusTransition,
)
from app.invoicing.supplier_matcher import match_supplier
from app.models import Invoice, InvoiceLineItem

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])

ACCEPTED_TYPES = {"pdf", "png", "jpg", "jpeg"}


def _ext_from_filename(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].lower()


def _invoice_to_list_item(inv: Invoice) -> InvoiceListItem:
    return InvoiceListItem(
        id=str(inv.id),
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        total_amount=float(inv.total_amount) if inv.total_amount is not None else None,
        currency=inv.currency,
        status=inv.status,
        supplier_id=str(inv.supplier_id) if inv.supplier_id else None,
        supplier_name_extracted=inv.supplier_name_extracted,
        needs_review=inv.needs_review,
        extraction_confidence=(
            float(inv.extraction_confidence) if inv.extraction_confidence is not None else None
        ),
        created_at=inv.created_at,
    )


def _line_item_to_detail(li: InvoiceLineItem) -> InvoiceLineItemDetail:
    return InvoiceLineItemDetail(
        id=str(li.id),
        invoice_id=str(li.invoice_id),
        description=li.description,
        quantity=float(li.quantity) if li.quantity is not None else None,
        unit_price=float(li.unit_price) if li.unit_price is not None else None,
        amount=float(li.amount) if li.amount is not None else None,
        po_number=li.po_number,
        material_number=li.material_number,
        raw_fields=li.raw_fields,
    )


def _invoice_to_detail(inv: Invoice) -> InvoiceDetail:
    return InvoiceDetail(
        id=str(inv.id),
        org_id=str(inv.org_id),
        supplier_id=str(inv.supplier_id) if inv.supplier_id else None,
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        subtotal=float(inv.subtotal) if inv.subtotal is not None else None,
        vat_rate=float(inv.vat_rate) if inv.vat_rate is not None else None,
        vat_amount=float(inv.vat_amount) if inv.vat_amount is not None else None,
        total_amount=float(inv.total_amount) if inv.total_amount is not None else None,
        currency=inv.currency,
        status=inv.status,
        file_url=inv.file_url,
        file_type=inv.file_type,
        original_filename=inv.original_filename,
        extraction_confidence=(
            float(inv.extraction_confidence) if inv.extraction_confidence is not None else None
        ),
        field_confidences=inv.field_confidences,
        needs_review=inv.needs_review,
        supplier_name_extracted=inv.supplier_name_extracted,
        extracted_at=inv.extracted_at,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        line_items=[_line_item_to_detail(li) for li in inv.line_items],
    )


@router.post("/upload", response_model=InvoiceUploadResponse, status_code=201)
async def upload_invoices(
    org_id: uuid.UUID,
    files: list[UploadFile],
    db: Session = Depends(get_db),
) -> InvoiceUploadResponse:
    """Batch upload invoice files. Creates Invoice records with status=received."""
    created: list[InvoiceListItem] = []

    for upload_file in files:
        ext = _ext_from_filename(upload_file.filename)
        if not ext or ext not in ACCEPTED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {upload_file.filename}. Accepted: {ACCEPTED_TYPES}",
            )

        content = await upload_file.read()
        _, relative_path = save_upload(content, ext, settings.invoice_upload_dir)

        invoice = Invoice(
            org_id=org_id,
            status="received",
            file_url=relative_path,
            file_type=ext,
            original_filename=upload_file.filename,
        )
        db.add(invoice)
        db.flush()
        created.append(_invoice_to_list_item(invoice))

    db.commit()
    return InvoiceUploadResponse(invoices=created, message=f"Uploaded {len(created)} invoice(s)")


@router.post("/{invoice_id}/extract", response_model=InvoiceDetail)
async def extract_invoice_data(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """Trigger OCR extraction on an uploaded invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status not in ("received", "extracted"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot extract from invoice with status '{invoice.status}'",
        )

    file_path = get_file_path(invoice.file_url, settings.invoice_upload_dir)

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="OCR service unavailable: no API key configured")

    result = await extract_invoice(
        file_path=file_path,
        file_type=invoice.file_type,
        api_key=settings.anthropic_api_key,
        model=settings.invoice_ocr_model,
    )

    if result.status == "error":
        raise HTTPException(status_code=500, detail=f"OCR extraction failed: {'; '.join(result.errors)}")

    # Update invoice fields from extraction
    fields = result.fields
    invoice.invoice_number = fields.get("invoice_number")
    invoice.supplier_name_extracted = fields.get("supplier_name")
    invoice.currency = fields.get("currency", "RMB") or "RMB"

    if fields.get("invoice_date"):
        try:
            invoice.invoice_date = date.fromisoformat(fields["invoice_date"])
        except (ValueError, TypeError):
            pass

    for numeric_field in ("subtotal", "vat_rate", "vat_amount", "total_amount"):
        val = fields.get(numeric_field)
        if val is not None:
            try:
                setattr(invoice, numeric_field, val)
            except (ValueError, TypeError):
                pass

    invoice.raw_extraction = result.raw_response
    invoice.extraction_confidence = result.overall_confidence
    invoice.field_confidences = result.field_confidences
    invoice.needs_review = any(
        c < 0.80 for c in result.field_confidences.values() if isinstance(c, (int, float))
    )
    invoice.extracted_at = datetime.now(timezone.utc)
    invoice.status = "extracted"

    # Create line items
    for li_data in result.line_items:
        li = InvoiceLineItem(
            invoice_id=invoice.id,
            description=li_data.get("description"),
            quantity=li_data.get("quantity"),
            unit_price=li_data.get("unit_price"),
            amount=li_data.get("amount"),
            po_number=li_data.get("po_number"),
            material_number=li_data.get("material_number"),
            raw_fields=li_data,
        )
        db.add(li)

    # Try to match supplier
    if invoice.supplier_name_extracted:
        supplier_id = match_supplier(invoice.supplier_name_extracted, invoice.org_id, db)
        if supplier_id:
            invoice.supplier_id = supplier_id

    db.commit()
    db.refresh(invoice)
    return _invoice_to_detail(invoice)


@router.get("/", response_model=list[InvoiceListItem])
def list_invoices(
    org_id: uuid.UUID,
    status: str | None = None,
    supplier_id: uuid.UUID | None = None,
    needs_review: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[InvoiceListItem]:
    """List invoices with optional filters."""
    q = db.query(Invoice).filter(Invoice.org_id == org_id)

    if status:
        q = q.filter(Invoice.status == status)
    if supplier_id:
        q = q.filter(Invoice.supplier_id == supplier_id)
    if needs_review is not None:
        q = q.filter(Invoice.needs_review == needs_review)
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)

    q = q.order_by(Invoice.created_at.desc())
    invoices = q.offset(offset).limit(limit).all()
    return [_invoice_to_list_item(inv) for inv in invoices]


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """Get invoice detail with nested line items."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _invoice_to_detail(invoice)


@router.put("/{invoice_id}", response_model=InvoiceDetail)
def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceUpdate,
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """Update extracted fields (manual correction)."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(invoice, field_name, value)

    # Re-attempt supplier matching if supplier name changed
    if "supplier_name_extracted" in update_data and update_data["supplier_name_extracted"]:
        supplier_id = match_supplier(update_data["supplier_name_extracted"], invoice.org_id, db)
        if supplier_id:
            invoice.supplier_id = supplier_id

    db.commit()
    db.refresh(invoice)
    return _invoice_to_detail(invoice)


@router.put("/{invoice_id}/status", response_model=InvoiceDetail)
def transition_status(
    invoice_id: uuid.UUID,
    body: StatusTransition,
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """Transition invoice status with validation."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    allowed = ALLOWED_TRANSITIONS.get(invoice.status, [])
    if body.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{invoice.status}' to '{body.status}'. "
            f"Allowed: {allowed}",
        )

    invoice.status = body.status
    db.commit()
    db.refresh(invoice)
    return _invoice_to_detail(invoice)


@router.get("/{invoice_id}/line-items", response_model=list[InvoiceLineItemDetail])
def get_line_items(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[InvoiceLineItemDetail]:
    """Get line items for an invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    items = db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id == invoice_id).all()
    return [_line_item_to_detail(li) for li in items]


@router.put("/{invoice_id}/line-items/{line_id}", response_model=InvoiceLineItemDetail)
def update_line_item(
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    body: InvoiceLineItemUpdate,
    db: Session = Depends(get_db),
) -> InvoiceLineItemDetail:
    """Update a specific line item."""
    li = (
        db.query(InvoiceLineItem)
        .filter(InvoiceLineItem.id == line_id, InvoiceLineItem.invoice_id == invoice_id)
        .first()
    )
    if not li:
        raise HTTPException(status_code=404, detail="Line item not found")

    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(li, field_name, value)

    db.commit()
    db.refresh(li)
    return _line_item_to_detail(li)
