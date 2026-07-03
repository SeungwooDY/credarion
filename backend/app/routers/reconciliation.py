"""API endpoints for the reconciliation engine."""
from __future__ import annotations

import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.auth_deps import authorize_supplier, get_current_user
from app.db import get_db
from app.models import (
    ERPRecord,
    Organization,
    ReconciliationConfig,
    ReconciliationResult,
    ReconciliationRun,
    StatementLineItem,
    Supplier,
    SupplierStatement,
    User,
)
from app.reconciliation.orchestrator import run_reconciliation
from app.reconciliation.schemas import (
    ApproveRequest,
    BulkResolveRequest,
    ConfigResponse,
    ConfigUpdate,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
    RejectRequest,
    ResolveRequest,
    ResultDetail,
    ReviewActionResponse,
    RunSummary,
    SupplierReconciliationSummary,
)

# Statuses that count as already-reviewed (cannot be re-approved/re-rejected).
_REVIEWED_STATUSES = {"confirmed", "rejected"}

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])


# --- Helpers ---


def _run_to_summary(run: ReconciliationRun, db: Session | None = None) -> RunSummary:
    erp_not_in_stmt = 0
    if db and run.id:
        erp_not_in_stmt = (
            db.query(func.count(ReconciliationResult.id))
            .filter(
                ReconciliationResult.run_id == run.id,
                ReconciliationResult.match_type == "unmatched",
                ReconciliationResult.discrepancy_type == "missing_from_statement",
            )
            .scalar() or 0
        )
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
        erp_not_in_statement=erp_not_in_stmt,
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
        confidence_score=r.confidence_score if r.confidence_score is not None else 0,
        confidence_label=r.confidence_label,
        sort_priority=r.sort_priority if r.sort_priority is not None else 99,
        discrepancy_note=r.discrepancy_note,
        amount=(r.match_details or {}).get("amount"),
        reviewer_id=r.reviewer_id,
        reviewed_at=r.reviewed_at,
        resolution_note=r.resolution_note,
        resolved_by=r.resolved_by,
        resolved_at=r.resolved_at,
        match_details=r.match_details,
        created_at=r.created_at,
    )


# --- Endpoints ---


@router.get("/suppliers-ready")
def list_suppliers_with_readiness(
    org_id: uuid.UUID = Query(...),
    period: str = Query(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List suppliers with their reconciliation readiness for a given period.

    Returns suppliers that have ERP records OR statements for the period,
    with counts and a ready flag (true when both ERP and statement exist).
    Uses bulk queries for performance with large supplier lists.
    """
    from sqlalchemy import case, literal_column
    from app.reconciliation.orchestrator import _period_date_range

    period_start, period_end = _period_date_range(period)

    # Bulk query: ERP counts per supplier
    erp_counts = dict(
        db.query(ERPRecord.supplier_id, func.count(ERPRecord.id))
        .join(Supplier, ERPRecord.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            ERPRecord.grn_date >= period_start,
            ERPRecord.grn_date <= period_end,
        )
        .group_by(ERPRecord.supplier_id)
        .all()
    )

    # Bulk query: statement row counts per supplier
    stmt_counts = dict(
        db.query(SupplierStatement.supplier_id, func.count(StatementLineItem.id))
        .join(StatementLineItem, StatementLineItem.statement_id == SupplierStatement.id)
        .join(Supplier, SupplierStatement.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            SupplierStatement.period == period,
        )
        .group_by(SupplierStatement.supplier_id)
        .all()
    )

    # Bulk query: latest reconciliation run per supplier
    from sqlalchemy.orm import aliased
    latest_runs = {}
    runs = (
        db.query(ReconciliationRun)
        .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            ReconciliationRun.period == period,
        )
        .order_by(ReconciliationRun.supplier_id, desc(ReconciliationRun.started_at))
        .all()
    )
    for r in runs:
        if r.supplier_id not in latest_runs:
            latest_runs[r.supplier_id] = r

    # Bulk query: review-status breakdown per supplier (latest run only).
    from collections import defaultdict

    run_id_by_supplier = {sid: run.id for sid, run in latest_runs.items()}
    latest_run_ids = list(run_id_by_supplier.values())
    status_by_run: dict[Any, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    near_exact_by_run: dict[Any, int] = defaultdict(int)
    if latest_run_ids:
        for rid, st, cnt in (
            db.query(
                ReconciliationResult.run_id,
                ReconciliationResult.status,
                func.count(ReconciliationResult.id),
            )
            .filter(ReconciliationResult.run_id.in_(latest_run_ids))
            .group_by(ReconciliationResult.run_id, ReconciliationResult.status)
            .all()
        ):
            status_by_run[rid][st] = cnt
        for rid, cnt in (
            db.query(ReconciliationResult.run_id, func.count(ReconciliationResult.id))
            .filter(
                ReconciliationResult.run_id.in_(latest_run_ids),
                ReconciliationResult.match_type == "near_exact",
            )
            .group_by(ReconciliationResult.run_id)
            .all()
        ):
            near_exact_by_run[rid] = cnt

    # Build result from suppliers that have any data
    supplier_ids_with_data = set(erp_counts.keys()) | set(stmt_counts.keys())
    suppliers = (
        db.query(Supplier)
        .filter(Supplier.org_id == org_id, Supplier.id.in_(supplier_ids_with_data))
        .all()
    )

    result = []
    for s in suppliers:
        erp_count = erp_counts.get(s.id, 0)
        stmt_rows = stmt_counts.get(s.id, 0)
        latest_run = latest_runs.get(s.id)

        rid = run_id_by_supplier.get(s.id)
        sc = status_by_run.get(rid, {})

        result.append({
            "id": str(s.id),
            "name": s.name,
            "vendor_code": s.vendor_code,
            "erp_count": erp_count,
            "statement_rows": stmt_rows,
            "has_erp": erp_count > 0,
            "has_statement": stmt_rows > 0,
            "ready": erp_count > 0 and stmt_rows > 0,
            "last_match_rate": float(latest_run.auto_match_rate) if latest_run and latest_run.auto_match_rate is not None else None,
            "last_run_status": latest_run.status if latest_run else None,
            # Review-queue breakdown for the latest run (0 if no run yet).
            "total_lines": sum(sc.values()),
            "pending_review": sc.get("pending_review", 0),
            "confirmed": sc.get("confirmed", 0),
            "rejected": sc.get("rejected", 0),
            "unmatched": sc.get("unmatched", 0),
            "near_exact_count": near_exact_by_run.get(rid, 0),
            "has_near_exact": near_exact_by_run.get(rid, 0) > 0,
        })

    # Sort: ready first, then by name
    result.sort(key=lambda x: (not x["ready"], x["name"]))
    return result


@router.get("/dashboard")
def dashboard_overview(
    org_id: uuid.UUID | None = Query(None),
    period: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Per-supplier overview for the home dashboard.

    When ``org_id`` / ``period`` are omitted this auto-selects the first
    organization and the most recent period that has reconciliation data, so the
    dashboard "just works" for a single-org pilot. Each row carries monetary
    ERP/statement totals, the unresolved discrepancy value, a coarse status, and
    the action the user should take.
    """
    from collections import defaultdict

    from app.reconciliation.orchestrator import _period_date_range

    # --- Auto-select org + period when not provided ---
    if org_id is None:
        first_org = db.query(Organization).first()
        if first_org is None:
            return []
        org_id = first_org.id

    if period is None:
        latest_run_period = (
            db.query(ReconciliationRun.period)
            .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
            .filter(Supplier.org_id == org_id, ReconciliationRun.status == "completed")
            .order_by(desc(ReconciliationRun.period))
            .first()
        )
        if latest_run_period:
            period = latest_run_period[0]
        else:
            latest_stmt_period = (
                db.query(SupplierStatement.period)
                .join(Supplier, SupplierStatement.supplier_id == Supplier.id)
                .filter(Supplier.org_id == org_id)
                .order_by(desc(SupplierStatement.period))
                .first()
            )
            if latest_stmt_period is None:
                return []
            period = latest_stmt_period[0]

    period_start, period_end = _period_date_range(period)

    # --- Monetary totals per supplier (ERP by grn_date window, statement by period) ---
    erp_agg: dict[uuid.UUID, tuple[float, int]] = {}
    for sid, amt, cnt in (
        db.query(
            ERPRecord.supplier_id,
            func.sum(ERPRecord.amount),
            func.count(ERPRecord.id),
        )
        .join(Supplier, ERPRecord.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            ERPRecord.grn_date >= period_start,
            ERPRecord.grn_date <= period_end,
        )
        .group_by(ERPRecord.supplier_id)
        .all()
    ):
        erp_agg[sid] = (float(amt or 0), cnt)

    stmt_agg: dict[uuid.UUID, tuple[float, int]] = {}
    for sid, amt, cnt in (
        db.query(
            SupplierStatement.supplier_id,
            func.sum(StatementLineItem.amount),
            func.count(StatementLineItem.id),
        )
        .join(StatementLineItem, StatementLineItem.statement_id == SupplierStatement.id)
        .join(Supplier, SupplierStatement.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            SupplierStatement.period == period,
        )
        .group_by(SupplierStatement.supplier_id)
        .all()
    ):
        stmt_agg[sid] = (float(amt or 0), cnt)

    supplier_ids = set(erp_agg) | set(stmt_agg)
    if not supplier_ids:
        return []

    # --- Latest completed run + its discrepancy results per supplier ---
    latest_runs: dict[uuid.UUID, ReconciliationRun] = {}
    for run in (
        db.query(ReconciliationRun)
        .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            ReconciliationRun.period == period,
            ReconciliationRun.status == "completed",
        )
        .order_by(ReconciliationRun.supplier_id, desc(ReconciliationRun.started_at))
        .all()
    ):
        if run.supplier_id not in latest_runs:
            latest_runs[run.supplier_id] = run

    run_ids = [r.id for r in latest_runs.values()]
    disc_by_supplier: dict[uuid.UUID, list[ReconciliationResult]] = defaultdict(list)
    erp_amt_map: dict[uuid.UUID, float] = {}
    stmt_amt_map: dict[uuid.UUID, float] = {}
    if run_ids:
        disc_results = (
            db.query(ReconciliationResult)
            .filter(
                ReconciliationResult.run_id.in_(run_ids),
                ReconciliationResult.discrepancy_type.isnot(None),
            )
            .all()
        )
        for r in disc_results:
            disc_by_supplier[r.supplier_id].append(r)

        erp_ids = [r.erp_record_id for r in disc_results if r.erp_record_id]
        stmt_ids = [r.statement_line_id for r in disc_results if r.statement_line_id]
        if erp_ids:
            for rid, amt in db.query(ERPRecord.id, ERPRecord.amount).filter(ERPRecord.id.in_(erp_ids)).all():
                erp_amt_map[rid] = float(amt or 0)
        if stmt_ids:
            for rid, amt in db.query(StatementLineItem.id, StatementLineItem.amount).filter(StatementLineItem.id.in_(stmt_ids)).all():
                stmt_amt_map[rid] = float(amt or 0)

    def _issue_value(r: ReconciliationResult) -> float:
        """Money at risk for one unresolved discrepancy.

        Uses the amount delta when present (qty/price/amount mismatches); for an
        item missing from one side, falls back to that side's line amount.
        """
        if r.amount_delta is not None and float(r.amount_delta) != 0:
            return abs(float(r.amount_delta))
        if r.erp_record_id and r.erp_record_id in erp_amt_map:
            return erp_amt_map[r.erp_record_id]
        if r.statement_line_id and r.statement_line_id in stmt_amt_map:
            return stmt_amt_map[r.statement_line_id]
        md = r.match_details or {}
        try:
            return abs(float(md.get("amount") or 0))
        except (TypeError, ValueError):
            return 0.0

    suppliers = {
        s.id: s
        for s in db.query(Supplier)
        .filter(Supplier.org_id == org_id, Supplier.id.in_(supplier_ids))
        .all()
    }

    status_rank = {"error": 0, "discrepancy": 1, "pending": 2, "in_review": 3, "matched": 4}
    rows: list[dict] = []
    for sid in supplier_ids:
        s = suppliers.get(sid)
        if s is None:
            continue
        erp_sum, erp_count = erp_agg.get(sid, (0.0, 0))
        stmt_sum, stmt_count = stmt_agg.get(sid, (0.0, 0))
        has_erp = erp_count > 0
        has_stmt = stmt_count > 0
        run = latest_runs.get(sid)

        items = disc_by_supplier.get(sid, [])
        unresolved = [i for i in items if i.status != "resolved"]
        # missing_from_erp = on statement, absent from ERP ("not in ERP")
        not_in_erp = sum(1 for i in unresolved if i.discrepancy_type == "missing_from_erp")
        not_in_stmt = sum(1 for i in unresolved if i.discrepancy_type == "missing_from_statement")
        qty_issues = sum(1 for i in unresolved if i.discrepancy_type and "quantity" in i.discrepancy_type)
        price_issues = sum(1 for i in unresolved if i.discrepancy_type and "price" in i.discrepancy_type)
        disc_value = sum(_issue_value(i) for i in unresolved)

        if not (has_erp and has_stmt):
            status, action = "pending", "upload"
        elif run is None:
            status, action = "pending", "review"
        elif run.status == "failed":
            status, action = "error", "review"
        elif unresolved:
            status, action = "discrepancy", "review"
        else:
            status, action = "matched", "none"

        detail_parts: list[str] = []
        if not has_erp:
            detail_parts.append("No ERP records")
        elif not has_stmt:
            detail_parts.append("No supplier statement")
        else:
            if not_in_erp:
                detail_parts.append(f"{not_in_erp} not in ERP")
            if not_in_stmt:
                detail_parts.append(f"{not_in_stmt} not in statement")
            if qty_issues:
                noun = "discrepancy" if qty_issues == 1 else "discrepancies"
                detail_parts.append(f"{qty_issues} qty {noun}")
            if price_issues:
                noun = "discrepancy" if price_issues == 1 else "discrepancies"
                detail_parts.append(f"{price_issues} price {noun}")
        details = " · ".join(detail_parts) if detail_parts else None

        rows.append({
            "vendor_code": s.vendor_code,
            "name": s.name,
            "display_name": s.name,
            "pinyin": s.vendor_code,
            "status": status,
            "erp_total": round(erp_sum, 2) if has_erp else None,
            "statement_total": round(stmt_sum, 2) if has_stmt else None,
            "discrepancy_value": round(disc_value, 2),
            "discrepancy_details": details,
            "action_required": action,
        })

    rows.sort(key=lambda x: (status_rank.get(x["status"], 9), -(x["discrepancy_value"] or 0), x["name"]))
    return rows


@router.post("/run", response_model=ReconciliationRunResponse, status_code=201)
async def trigger_reconciliation(
    body: ReconciliationRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReconciliationRunResponse:
    """Trigger reconciliation for a supplier+period."""
    authorize_supplier(db, user, body.supplier_id)
    # Clean up stale "running" runs (stuck for > 5 minutes) before checking
    from datetime import timedelta
    stale_cutoff = datetime.utcnow() - timedelta(minutes=5)
    stale_runs = (
        db.query(ReconciliationRun)
        .filter(
            ReconciliationRun.supplier_id == body.supplier_id,
            ReconciliationRun.period == body.period,
            ReconciliationRun.status == "running",
            ReconciliationRun.started_at < stale_cutoff,
        )
        .all()
    )
    for stale in stale_runs:
        stale.status = "failed"
        stale.completed_at = datetime.utcnow()
    if stale_runs:
        db.commit()

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

    return ReconciliationRunResponse(run=_run_to_summary(run, db))


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
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
    return [_run_to_summary(r, db) for r in runs]


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> RunSummary:
    """Get run detail with summary stats."""
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_summary(run, db)


@router.get("/results", response_model=list[ResultDetail])
def list_results(
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
def get_result(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ResultDetail:
    """Get a single reconciliation result."""
    r = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    return _result_to_detail(r)


@router.put("/results/{result_id}/resolve", response_model=ResultDetail)
def resolve_result(
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
def bulk_resolve(
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
def reconciliation_summary(
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
def export_results(
    run_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    period: str | None = None,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Download discrepancy report as Excel or CSV."""
    import pandas as pd

    # Export everything carrying a discrepancy (near_exact, unmatched, or any
    # layer match with nonzero deltas), regardless of review status.
    q = db.query(ReconciliationResult).filter(
        ReconciliationResult.discrepancy_type.isnot(None)
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


@router.get("/mismatches")
def list_mismatches(
    org_id: uuid.UUID = Query(...),
    period: str = Query(...),
    supplier_id: uuid.UUID | None = None,
    include_matches: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return mismatched/discrepancy results grouped by supplier with enriched ERP+statement data.

    Each supplier entry includes summary counts and individual mismatch items
    with PO number, material number, quantities, prices, and amounts from both sides.

    When ``include_matches`` is true, clean matched line items (no discrepancy)
    are returned alongside the mismatches so the UI can show/export everything.
    Summary counts (``total_mismatches`` etc.) always reflect mismatches only;
    matched rows are counted separately in ``total_matches``.
    """
    from app.reconciliation.orchestrator import _period_date_range

    # Find the latest run per supplier for this period
    latest_runs_q = (
        db.query(ReconciliationRun)
        .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
        .filter(
            Supplier.org_id == org_id,
            ReconciliationRun.period == period,
            ReconciliationRun.status == "completed",
        )
    )
    if supplier_id:
        latest_runs_q = latest_runs_q.filter(ReconciliationRun.supplier_id == supplier_id)

    latest_runs_q = latest_runs_q.order_by(
        ReconciliationRun.supplier_id, desc(ReconciliationRun.started_at)
    )
    # Deduplicate to latest run per supplier
    latest_runs: dict[uuid.UUID, ReconciliationRun] = {}
    for run in latest_runs_q.all():
        if run.supplier_id not in latest_runs:
            latest_runs[run.supplier_id] = run

    if not latest_runs:
        return []

    # Fetch results for these runs. By default only discrepancies; when
    # include_matches is set, also pull clean matched rows (discrepancy_type NULL).
    run_ids = [r.id for r in latest_runs.values()]
    results_q = db.query(ReconciliationResult).filter(
        ReconciliationResult.run_id.in_(run_ids),
    )
    if not include_matches:
        results_q = results_q.filter(ReconciliationResult.discrepancy_type.isnot(None))
    results = results_q.all()

    if not results:
        return []

    # Bulk-load related ERP records and statement line items
    erp_ids = [r.erp_record_id for r in results if r.erp_record_id]
    stmt_ids = [r.statement_line_id for r in results if r.statement_line_id]

    erp_map: dict[uuid.UUID, ERPRecord] = {}
    if erp_ids:
        for e in db.query(ERPRecord).filter(ERPRecord.id.in_(erp_ids)).all():
            erp_map[e.id] = e

    stmt_map: dict[uuid.UUID, StatementLineItem] = {}
    if stmt_ids:
        for s in db.query(StatementLineItem).filter(StatementLineItem.id.in_(stmt_ids)).all():
            stmt_map[s.id] = s

    # Load supplier info
    supplier_ids = list(latest_runs.keys())
    suppliers = {
        s.id: s
        for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()
    }

    # Group results by supplier
    from collections import defaultdict
    by_supplier: dict[uuid.UUID, list] = defaultdict(list)
    for r in results:
        erp = erp_map.get(r.erp_record_id) if r.erp_record_id else None
        stmt = stmt_map.get(r.statement_line_id) if r.statement_line_id else None

        item = {
            "id": str(r.id),
            "match_type": r.match_type,
            "status": r.status,
            "discrepancy_type": r.discrepancy_type,
            "quantity_delta": float(r.quantity_delta) if r.quantity_delta is not None else None,
            "price_delta": float(r.price_delta) if r.price_delta is not None else None,
            "amount_delta": float(r.amount_delta) if r.amount_delta is not None else None,
            "confidence": float(r.confidence) if r.confidence is not None else None,
            "resolution_note": r.resolution_note,
            "erp": {
                "po_number": erp.po_number,
                "material_number": erp.material_number,
                "quantity": float(erp.quantity),
                "po_price": float(erp.po_price),
                "amount": float(erp.amount),
                "grn_date": erp.grn_date.isoformat() if erp.grn_date else None,
            } if erp else None,
            "statement": {
                "po_number": stmt.po_number,
                "material_number": stmt.material_number,
                "quantity": float(stmt.quantity),
                "unit_price": float(stmt.unit_price),
                "amount": float(stmt.amount),
                "delivery_date": stmt.delivery_date.isoformat() if stmt.delivery_date else None,
            } if stmt else None,
        }
        by_supplier[r.supplier_id].append(item)

    # Build response
    result_list = []
    for sid, items in by_supplier.items():
        s = suppliers.get(sid)
        run = latest_runs.get(sid)
        if not s or not run:
            continue

        unmatched_erp = sum(1 for i in items if i["discrepancy_type"] == "missing_from_statement")
        unmatched_stmt = sum(1 for i in items if i["discrepancy_type"] == "missing_from_erp")
        qty_issues = sum(1 for i in items if i["discrepancy_type"] and "quantity" in i["discrepancy_type"])
        price_issues = sum(1 for i in items if i["discrepancy_type"] and "price" in i["discrepancy_type"])
        mismatch_count = sum(1 for i in items if i["discrepancy_type"])
        match_count = sum(1 for i in items if not i["discrepancy_type"])

        result_list.append({
            "supplier_id": str(sid),
            "supplier_name": s.name,
            "vendor_code": s.vendor_code,
            "run_id": str(run.id),
            "match_rate": float(run.auto_match_rate) if run.auto_match_rate is not None else None,
            "total_erp": run.total_erp,
            "total_statement": run.total_statement,
            "total_mismatches": mismatch_count,
            "total_matches": match_count,
            "unmatched_erp": unmatched_erp,
            "unmatched_stmt": unmatched_stmt,
            "qty_issues": qty_issues,
            "price_issues": price_issues,
            "items": items,
        })

    # Sort by total mismatches descending
    result_list.sort(key=lambda x: x["total_mismatches"], reverse=True)
    return result_list


@router.get("/config/{org_id}", response_model=ConfigResponse)
def get_config(
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
def update_config(
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


# --- Human review queue ------------------------------------------------------
#
# NOTE: the routes below use bare path params ({supplier_id}/{period} and
# {result_id}/...). They are declared LAST so FastAPI matches the literal
# routes above (/runs/..., /results/..., /config/...) first and these only
# catch genuine UUID/period paths.


@router.post("/{result_id}/approve", response_model=ReviewActionResponse)
def approve_result(
    result_id: uuid.UUID,
    body: ApproveRequest,
    db: Session = Depends(get_db),
) -> ReviewActionResponse:
    """Confirm a matched result during human review.

    Sets status='confirmed', records the reviewer and timestamp.
    409 if the result was already confirmed/rejected; 404 if not found.
    """
    r = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    if r.status in _REVIEWED_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Result already {r.status}"
        )

    r.status = "confirmed"
    r.reviewer_id = body.reviewer_id
    r.reviewed_at = datetime.utcnow()
    if body.note:
        r.resolution_note = body.note
    db.commit()
    return ReviewActionResponse(id=str(r.id), status="confirmed")


@router.post("/{result_id}/reject", response_model=ReviewActionResponse)
def reject_result(
    result_id: uuid.UUID,
    body: RejectRequest,
    db: Session = Depends(get_db),
) -> ReviewActionResponse:
    """Flag a result as a discrepancy during human review.

    Requires a non-empty reason (stored in discrepancy_note). Sets
    status='rejected', records reviewer + timestamp.
    400 if reason is empty; 409 if already confirmed/rejected; 404 if not found.
    """
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A rejection reason is required")

    r = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    if r.status in _REVIEWED_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Result already {r.status}"
        )

    r.status = "rejected"
    r.reviewer_id = body.reviewer_id
    r.reviewed_at = datetime.utcnow()
    r.discrepancy_note = reason
    db.commit()
    return ReviewActionResponse(id=str(r.id), status="rejected")


@router.get("/{supplier_id}/{period}", response_model=list[ResultDetail])
def review_queue(
    supplier_id: uuid.UUID,
    period: str,
    db: Session = Depends(get_db),
) -> list[ResultDetail]:
    """Human review queue for a supplier+period (latest run).

    Sorted by sort_priority ASC (highest confidence first), then amount DESC
    (largest value items first) within each confidence group.
    """
    latest_run = (
        db.query(ReconciliationRun)
        .filter(
            ReconciliationRun.supplier_id == supplier_id,
            ReconciliationRun.period == period,
        )
        .order_by(desc(ReconciliationRun.started_at))
        .first()
    )
    if not latest_run:
        return []

    results = (
        db.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == latest_run.id)
        .all()
    )

    def _amount(r: ReconciliationResult) -> float:
        amt = (r.match_details or {}).get("amount")
        return float(amt) if amt is not None else 0.0

    results.sort(
        key=lambda r: (
            r.sort_priority if r.sort_priority is not None else 99,
            -_amount(r),
        )
    )
    return [_result_to_detail(r) for r in results]
