"""
SQLAlchemy models for Credarion supplier reconciliation.

Schema mirrors the Technical Build Handoff (April 2026) with these approved deltas:
  - erp_records.quantity and statement_line_items.quantity are NUMERIC(14,3), not INTEGER
  - erp_records and statement_line_items carry a raw_row JSONB column for audit/recovery
  - No delivery_notes table (dn_no lives as a column; multi-PO DN handled at match time)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RMB")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    suppliers: Mapped[list["Supplier"]] = relationship(back_populates="organization")
    erp_records: Mapped[list["ERPRecord"]] = relationship(back_populates="organization")


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("org_id", "vendor_code", name="uq_suppliers_org_vendor_code"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    vendor_code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    is_cross_border: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="suppliers")
    erp_records: Mapped[list["ERPRecord"]] = relationship(back_populates="supplier")
    statements: Mapped[list["SupplierStatement"]] = relationship(back_populates="supplier")


class ERPRecord(Base):
    __tablename__ = "erp_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )

    po_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    material_number: Mapped[str] = mapped_column(String, nullable=False, index=True)

    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    po_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    grn_number: Mapped[str] = mapped_column(String, nullable=False)
    grn_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    delivery_order: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_note: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    source_file: Mapped[str] = mapped_column(String, nullable=False)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="erp_records")
    supplier: Mapped[Supplier] = relationship(back_populates="erp_records")


class SupplierStatement(Base):
    __tablename__ = "supplier_statements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "2026-03"
    file_url: Mapped[str] = mapped_column(String, nullable=False)
    upload_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    supplier: Mapped[Supplier] = relationship(back_populates="statements")
    line_items: Mapped[list["StatementLineItem"]] = relationship(back_populates="statement")


class StatementLineItem(Base):
    __tablename__ = "statement_line_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    statement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_statements.id", ondelete="CASCADE"),
        nullable=False,
    )

    po_number: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    material_number: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    delivery_date: Mapped[date | None] = mapped_column(nullable=True)
    delivery_note_ref: Mapped[str | None] = mapped_column(String, nullable=True)

    raw_row: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    statement: Mapped[SupplierStatement] = relationship(back_populates="line_items")


class SupplierColumnMapping(Base):
    __tablename__ = "supplier_column_mappings"
    __table_args__ = (
        UniqueConstraint("supplier_id", name="uq_supplier_column_mappings_supplier_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    column_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # alias | llm | manual
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    header_row: Mapped[int] = mapped_column(Integer, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    supplier: Mapped[Supplier] = relationship()


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String, nullable=False)
    # status: running | completed | failed
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")

    total_erp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_statement: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_match_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    supplier: Mapped[Supplier] = relationship()
    results: Mapped[list["ReconciliationResult"]] = relationship(back_populates="run")


class ReconciliationConfig(Base):
    __tablename__ = "reconciliation_config"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_reconciliation_config_org_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    qty_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.50")
    )
    price_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.50")
    )
    auto_resolve_exact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_layer_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_max_tokens_per_run: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship()


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String, nullable=False)

    erp_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp_records.id", ondelete="SET NULL"), nullable=True
    )
    statement_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("statement_line_items.id", ondelete="SET NULL"),
        nullable=True,
    )

    # match_type: exact | fuzzy | multi_po_dn | ai | unmatched
    match_type: Mapped[str] = mapped_column(String, nullable=False)
    quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    price_delta: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    amount_delta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # discrepancy_type: quantity_over | quantity_under | price_higher | price_lower |
    #                   missing_from_erp | missing_from_statement
    discrepancy_type: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    # status: matched | discrepancy | resolved
    status: Mapped[str] = mapped_column(String, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    match_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[ReconciliationRun | None] = relationship(back_populates="results")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )

    invoice_number: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    invoice_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)

    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RMB")

    # status: received → extracted → matched → approved → paid
    status: Mapped[str] = mapped_column(String, nullable=False, default="received", index=True)

    file_url: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)

    raw_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    field_confidences: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supplier_name_extracted: Mapped[str | None] = mapped_column(String, nullable=True)

    extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship()
    supplier: Mapped[Supplier | None] = relationship()
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )

    description: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    po_number: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    material_number: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    raw_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")
