"""API endpoints for the reconciliation engine."""
from __future__ import annotations

import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    ReconciliationConfig,
    ReconciliationResult,
    ReconciliationRun,
    Supplier,
)
from app.reconciliation.orchestrator import run_reconciliation
from app.reconciliation.schemas import (
    BulkResolveRequest,
    ConfigResponse,
    ConfigUpdate,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
    ResolveRequest,
    ResultDetail,
    RunSummary,
    SupplierReconciliationSummary,
)

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])


# --- Helpers ---


def _run_to_summary(run: ReconciliationRun) -> RunSummary:
    return RunSummary(
        id=str(run.id),
        supplier_id=str(run.supplier_id),
        supplier_name=run.supplier.name if run.supplier else None,
        period=run.period,
        status=run.status,
        total_erp=run.total_erp,
        total_statement=run.total_statement,
        matched_count=run.matched_count,
        discrepancy_count=run.discrepancy_count,
        unmatched_count=run.unmatched_count,
        auto_match_rate=float(run.auto_match_rate) if run.auto_match_rate is not None else None,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _result_to_detail(r: ReconciliationResult) -> ResultDetail:
    return ResultDetail(
        id=str(r.id),
        run_id=str(r.run_id) if r.run_id else None,
        supplier_id=str(r.supplier_id),
        period=r.period,
        erp_record_id=str(r.erp_record_id) if r.erp_record_id else None,
        statement_line_id=str(r.statement_line_id) if r.statement_line_id else None,
        match_type=r.match_type,
        quantity_delta=float(r.quantity_delta) if r.quantity_delta is not None else None,
        price_delta=float(r.price_delta) if r.price_delta is not None else None,
        amount_delta=float(r.amount_delta) if r.amount_delta is not None else None,
        discrepancy_type=r.discrepancy_type,
        confidence=float(r.confidence) if r.confidence is not None else None,
        status=r.status,
        resolution_note=r.resolution_note,
        resolved_by=r.resolved_by,
        resolved_at=r.resolved_at,
        match_details=r.match_details,
        created_at=r.created_at,
    )


# --- Endpoints ---


@router.post("/run", response_model=ReconciliationRunResponse, status_code=201)
async def trigger_reconciliation(
    body: ReconciliationRunRequest,
    db: Session = Depends(get_db),
) -> ReconciliationRunResponse:
    """Trigger reconciliation for a supplier+period."""
    # Check for existing running run
    existing = (
        db.query(ReconciliationRun)
        .filter(
            ReconciliationRun.supplier_id == body.supplier_id,
            ReconciliationRun.period == body.period,
            ReconciliationRun.status == "running",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Reconciliation already running for this supplier+period",
        )

    try:
        run = await run_reconciliation(body.supplier_id, body.period, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {e}")

    return ReconciliationRunResponse(run=_run_to_summary(run))


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    supplier_id: uuid.UUID | None = None,
    period: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[RunSummary]:
    """List reconciliation runs with optional filters."""
    q = db.query(ReconciliationRun)
    if supplier_id:
        q = q.filter(ReconciliationRun.supplier_id == supplier_id)
    if period:
        q = q.filter(ReconciliationRun.period == period)
    if status:
        q = q.filter(ReconciliationRun.status == status)
    runs = q.order_by(desc(ReconciliationRun.started_at)).offset(offset).limit(limit).all()
    return [_run_to_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> RunSummary:
    """Get run detail with summary stats."""
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_summary(run)


@router.get("/results", response_model=list[ResultDetail])
async def list_results(
    run_id: uuid.UUID | None = None,
    status: str | None = None,
    match_type: str | None = None,
    discrepancy_type: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ResultDetail]:
    """List reconciliation results with filters and pagination."""
    q = db.query(ReconciliationResult)
    if run_id:
        q = q.filter(ReconciliationResult.run_id == run_id)
    if status:
        q = q.filter(ReconciliationResult.status == status)
    if match_type:
        q = q.filter(ReconciliationResult.match_type == match_type)
    if discrepancy_type:
        q = q.filter(ReconciliationResult.discrepancy_type == discrepancy_type)
    results = q.order_by(ReconciliationResult.created_at).offset(offset).limit(limit).all()
    return [_result_to_detail(r) for r in results]


@router.get("/results/{result_id}", response_model=ResultDetail)
async def get_result(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ResultDetail:
    """Get a single reconciliation result."""
    r = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    return _result_to_detail(r)


@router.put("/results/{result_id}/resolve", response_model=ResultDetail)
async def resolve_result(
    result_id: uuid.UUID,
    body: ResolveRequest,
    db: Session = Depends(get_db),
) -> ResultDetail:
    """Resolve a discrepancy with a note."""
    r = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    if r.status == "resolved":
        raise HTTPException(status_code=400, detail="Already resolved")

    r.status = "resolved"
    r.resolution_note = body.resolution_note
    r.resolved_by = body.resolved_by
    r.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(r)
    return _result_to_detail(r)


@router.post("/results/bulk-resolve", response_model=list[ResultDetail])
async def bulk_resolve(
    body: BulkResolveRequest,
    db: Session = Depends(get_db),
) -> list[ResultDetail]:
    """Bulk resolve multiple results."""
    results = (
        db.query(ReconciliationResult)
        .filter(ReconciliationResult.id.in_(body.result_ids))
        .all()
    )
    if len(results) != len(body.result_ids):
        raise HTTPException(status_code=404, detail="Some results not found")

    now = datetime.utcnow()
    for r in results:
        if r.status != "resolved":
            r.status = "resolved"
            r.resolution_note = body.resolution_note
            r.resolved_by = body.resolved_by
            r.resolved_at = now
    db.commit()

    # Refresh and return
    refreshed = (
        db.query(ReconciliationResult)
        .filter(ReconciliationResult.id.in_(body.result_ids))
        .all()
    )
    return [_result_to_detail(r) for r in refreshed]


@router.get("/summary", response_model=list[SupplierReconciliationSummary])
async def reconciliation_summary(
    db: Session = Depends(get_db),
) -> list[SupplierReconciliationSummary]:
    """Get reconciliation status per supplier for the UI dashboard."""
    suppliers = db.query(Supplier).all()
    summaries = []
    for s in suppliers:
        latest_run = (
            db.query(ReconciliationRun)
            .filter(ReconciliationRun.supplier_id == s.id)
            .order_by(desc(ReconciliationRun.started_at))
            .first()
        )
        total_runs = (
            db.query(func.count(ReconciliationRun.id))
            .filter(ReconciliationRun.supplier_id == s.id)
            .scalar()
        )
        summaries.append(SupplierReconciliationSummary(
            supplier_id=str(s.id),
            supplier_name=s.name,
            latest_run_id=str(latest_run.id) if latest_run else None,
            latest_period=latest_run.period if latest_run else None,
            latest_status=latest_run.status if latest_run else None,
            latest_match_rate=(
                float(latest_run.auto_match_rate)
                if latest_run and latest_run.auto_match_rate is not None
                else None
            ),
            total_runs=total_runs or 0,
        ))
    return summaries


@router.get("/export")
async def export_results(
    run_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    period: str | None = None,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Download discrepancy report as Excel or CSV."""
    import pandas as pd

    q = db.query(ReconciliationResult).filter(
        ReconciliationResult.status.in_(["discrepancy", "resolved"])
    )
    if run_id:
        q = q.filter(ReconciliationResult.run_id == run_id)
    if supplier_id:
        q = q.filter(ReconciliationResult.supplier_id == supplier_id)
    if period:
        q = q.filter(ReconciliationResult.period == period)

    results = q.all()

    rows = []
    for r in results:
        rows.append({
            "Result ID": str(r.id),
            "Period": r.period,
            "Match Type": r.match_type,
            "Status": r.status,
            "Discrepancy Type": r.discrepancy_type or "",
            "Quantity Delta": float(r.quantity_delta) if r.quantity_delta else 0,
            "Price Delta": float(r.price_delta) if r.price_delta else 0,
            "Amount Delta": float(r.amount_delta) if r.amount_delta else 0,
            "Confidence": float(r.confidence) if r.confidence else "",
            "Resolution Note": r.resolution_note or "",
            "Resolved By": r.resolved_by or "",
        })

    df = pd.DataFrame(rows)
    buf = io.BytesIO()

    if format == "xlsx":
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=reconciliation_report.xlsx"},
        )
    else:
        content = df.to_csv(index=False)
        buf = io.BytesIO(content.encode("utf-8"))
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=reconciliation_report.csv"},
        )


@router.get("/config/{org_id}", response_model=ConfigResponse)
async def get_config(
    org_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ConfigResponse:
    """Get tolerance configuration for an organization."""
    config = (
        db.query(ReconciliationConfig)
        .filter(ReconciliationConfig.org_id == org_id)
        .first()
    )
    if not config:
        # Return defaults
        return ConfigResponse(
            org_id=str(org_id),
            qty_tolerance_pct=0.50,
            price_tolerance_pct=0.50,
            auto_resolve_exact=True,
            ai_layer_enabled=True,
            ai_max_tokens_per_run=10000,
        )
    return ConfigResponse(
        org_id=str(config.org_id),
        qty_tolerance_pct=float(config.qty_tolerance_pct),
        price_tolerance_pct=float(config.price_tolerance_pct),
        auto_resolve_exact=config.auto_resolve_exact,
        ai_layer_enabled=config.ai_layer_enabled,
        ai_max_tokens_per_run=config.ai_max_tokens_per_run,
    )


@router.put("/config/{org_id}", response_model=ConfigResponse)
async def update_config(
    org_id: uuid.UUID,
    body: ConfigUpdate,
    db: Session = Depends(get_db),
) -> ConfigResponse:
    """Create or update tolerance configuration for an organization."""
    config = (
        db.query(ReconciliationConfig)
        .filter(ReconciliationConfig.org_id == org_id)
        .first()
    )
    if not config:
        config = ReconciliationConfig(org_id=org_id)
        db.add(config)

    if body.qty_tolerance_pct is not None:
        config.qty_tolerance_pct = body.qty_tolerance_pct
    if body.price_tolerance_pct is not None:
        config.price_tolerance_pct = body.price_tolerance_pct
    if body.auto_resolve_exact is not None:
        config.auto_resolve_exact = body.auto_resolve_exact
    if body.ai_layer_enabled is not None:
        config.ai_layer_enabled = body.ai_layer_enabled
    if body.ai_max_tokens_per_run is not None:
        config.ai_max_tokens_per_run = body.ai_max_tokens_per_run

    db.commit()
    db.refresh(config)

    return ConfigResponse(
        org_id=str(config.org_id),
        qty_tolerance_pct=float(config.qty_tolerance_pct),
        price_tolerance_pct=float(config.price_tolerance_pct),
        auto_resolve_exact=config.auto_resolve_exact,
        ai_layer_enabled=config.ai_layer_enabled,
        ai_max_tokens_per_run=config.ai_max_tokens_per_run,
    )
