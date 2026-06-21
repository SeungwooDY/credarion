"""Pydantic schemas for reconciliation API request/response."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# --- Request schemas ---


class ReconciliationRunRequest(BaseModel):
    supplier_id: uuid.UUID
    period: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="Period in YYYY-MM format")


class ResolveRequest(BaseModel):
    resolution_note: str
    resolved_by: str = "user"


class BulkResolveRequest(BaseModel):
    result_ids: list[uuid.UUID]
    resolution_note: str
    resolved_by: str = "user"


class ConfigUpdate(BaseModel):
    qty_tolerance_pct: Decimal | None = None
    price_tolerance_pct: Decimal | None = None
    auto_resolve_exact: bool | None = None
    ai_layer_enabled: bool | None = None
    ai_max_tokens_per_run: int | None = None


class ApproveRequest(BaseModel):
    """Confirm a matched result during human review."""
    reviewer_id: str
    note: str | None = None


class RejectRequest(BaseModel):
    """Flag a result as a discrepancy during human review. Reason is required."""
    reviewer_id: str
    reason: str


# --- Response schemas ---


class RunSummary(BaseModel):
    id: str
    supplier_id: str
    supplier_name: str | None = None
    period: str
    status: str
    total_erp: int
    total_statement: int
    matched_count: int
    discrepancy_count: int
    unmatched_count: int
    erp_not_in_statement: int = 0
    auto_match_rate: float | None = None
    started_at: datetime
    completed_at: datetime | None = None


class ResultDetail(BaseModel):
    id: str
    run_id: str | None = None
    supplier_id: str
    period: str
    erp_record_id: str | None = None
    statement_line_id: str | None = None
    match_type: str
    quantity_delta: float | None = None
    price_delta: float | None = None
    amount_delta: float | None = None
    discrepancy_type: str | None = None
    confidence: float | None = None
    status: str
    # --- Human review queue ---
    confidence_score: int = 0
    confidence_label: str | None = None
    sort_priority: int = 99
    discrepancy_note: str | None = None
    amount: float | None = None
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None
    resolution_note: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    match_details: dict | None = None
    created_at: datetime


class ReviewActionResponse(BaseModel):
    """Minimal response for approve/reject actions."""
    id: str
    status: str


class SupplierReconciliationSummary(BaseModel):
    supplier_id: str
    supplier_name: str
    latest_run_id: str | None = None
    latest_period: str | None = None
    latest_status: str | None = None
    latest_match_rate: float | None = None
    total_runs: int = 0


class ConfigResponse(BaseModel):
    org_id: str
    qty_tolerance_pct: float
    price_tolerance_pct: float
    auto_resolve_exact: bool
    ai_layer_enabled: bool
    ai_max_tokens_per_run: int


class ReconciliationRunResponse(BaseModel):
    run: RunSummary
    message: str = "Reconciliation completed"
