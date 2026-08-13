"""API endpoints for SGWERP GRN (Goods Receipt Note) ingestion."""
from __future__ import annotations

import calendar
import json
import logging
import queue
import shutil
import tempfile
import threading
import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.auth_deps import authorize_org, get_current_user
from app.db import SessionLocal, get_db
from app.ingestion.grn_ingestor import GRNIngestionResult, ingest_grn
from app.models import ERPRecord, PeriodSignoff, SupplierStatement, User
from app.periods import validate_period
from app.reconciliation.auto_run import auto_reconcile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/erp", tags=["erp"])


def _recon_pairs(
    db: Session,
    org_id: uuid.UUID,
    affected: list[tuple[uuid.UUID, str]],
) -> list[tuple[uuid.UUID, str]]:
    """Filter (supplier, period) pairs touched by a GRN upload down to the
    ones worth auto-reconciling: a statement exists and the period is not
    signed off."""
    if not affected:
        return []
    locked = {
        p
        for (p,) in db.query(PeriodSignoff.period).filter(
            PeriodSignoff.org_id == org_id,
            PeriodSignoff.status == "signed_off",
        )
    }
    pairs: list[tuple[uuid.UUID, str]] = []
    for supplier_id, period in affected:
        if period in locked:
            continue
        has_statement = (
            db.query(SupplierStatement.id)
            .filter(
                SupplierStatement.supplier_id == supplier_id,
                SupplierStatement.period == period,
            )
            .first()
        )
        if has_statement:
            pairs.append((supplier_id, period))
    return pairs


async def _run_auto_recon(pairs: list[tuple[uuid.UUID, str]]) -> None:
    """Reconcile the pairs one at a time (serial keeps AI-credit use bounded)."""
    for supplier_id, period in pairs:
        await auto_reconcile(supplier_id, period)


class GRNIngestionResponse(BaseModel):
    status: str
    rows_ingested: int = 0
    rows_skipped: int = 0
    rows_duplicate: int = 0
    rows_replaced: int = 0
    suppliers_created: int = 0
    suppliers_existing: int = 0
    errors: list[str] = []
    # Period-mismatch detection: the month the batch was filed under, the
    # month the file's dates look like, and a warning when they disagree.
    period: str | None = None
    detected_period: str | None = None
    period_mismatch_pct: int = 0
    period_warning: str | None = None


class ERPStatusResponse(BaseModel):
    has_data: bool
    row_count: int


@router.get("/status", response_model=ERPStatusResponse)
def erp_status(
    org_id: uuid.UUID = Query(...),
    period: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ERPStatusResponse:
    """Whether the org has ERP/GRN rows uploaded for the given month.

    The ingestion page gates statement upload on this: ERP export first,
    then supplier statements (statements need the suppliers + receipts the
    GRN upload creates). Scoped by the upload's period tag; legacy untagged
    rows fall back to their grn_date month.
    """
    authorize_org(db, user, org_id)
    try:
        validate_period(period)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    year, month = map(int, period.split("-"))
    start = datetime(year, month, 1)
    end = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)
    count = (
        db.query(ERPRecord)
        .filter(
            ERPRecord.org_id == org_id,
            or_(
                ERPRecord.period == period,
                and_(
                    ERPRecord.period.is_(None),
                    ERPRecord.grn_date >= start,
                    ERPRecord.grn_date <= end,
                ),
            ),
        )
        .count()
    )
    return ERPStatusResponse(has_data=count > 0, row_count=count)


@router.post("/upload", response_model=GRNIngestionResponse, status_code=201)
def upload_grn(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    org_id: uuid.UUID = Form(...),
    replace: bool = Form(False),
    period: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GRNIngestionResponse:
    """Upload an SGWERP GRN export file for ingestion.

    Accepts .csv, .xlsx, or .xls files. Automatically maps columns,
    upserts suppliers, normalizes data, and inserts erp_records.

    With ``replace=true``, rows already in the DB (same supplier + PO +
    material + GRN number) are purged and re-ingested instead of skipped —
    use to recapture full decimal precision for pre-0009 uploads. Re-run
    reconciliation afterwards.
    """
    authorize_org(db, user, org_id)
    if period is not None:
        try:
            validate_period(period)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    suffix = (
        "." + file.filename.rsplit(".", 1)[-1]
        if file.filename and "." in file.filename
        else ".csv"
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    result: GRNIngestionResult = ingest_grn(
        file_path=tmp_path,
        org_id=org_id,
        db=db,
        replace=replace,
        period=period,
    )

    response = GRNIngestionResponse(
        status=result.status,
        rows_ingested=result.rows_ingested,
        rows_skipped=result.rows_skipped,
        rows_duplicate=result.rows_duplicate,
        rows_replaced=result.rows_replaced,
        suppliers_created=result.suppliers_created,
        suppliers_existing=result.suppliers_existing,
        errors=result.errors,
        period=result.period,
        detected_period=result.detected_period,
        period_mismatch_pct=result.period_mismatch_pct,
        period_warning=result.period_warning,
    )

    if result.status == "error":
        raise HTTPException(status_code=400, detail=response.model_dump())

    # Auto-rerun reconciliation for supplier+periods this upload touched that
    # already have a statement (skipping signed-off months).
    pairs = _recon_pairs(db, org_id, result.affected_periods)
    if pairs:
        background_tasks.add_task(_run_auto_recon, pairs)

    return response


@router.post("/upload-stream")
def upload_grn_stream(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    org_id: uuid.UUID = Form(...),
    replace: bool = Form(False),
    period: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Upload GRN with SSE progress events.

    Returns a text/event-stream with progress updates during ingestion.
    Final event contains the full result. After the stream closes,
    reconciliation auto-reruns for affected supplier+periods that already
    have a statement.
    """
    authorize_org(db, user, org_id)
    if period is not None:
        try:
            validate_period(period)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    suffix = (
        "." + file.filename.rsplit(".", 1)[-1]
        if file.filename and "." in file.filename
        else ".csv"
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    progress_queue: queue.Queue = queue.Queue()

    def on_progress(phase: str, current: int, total: int, message: str) -> None:
        progress_queue.put({
            "type": "progress",
            "phase": phase,
            "current": current,
            "total": total,
            "message": message,
        })

    # Populated by the ingestion thread; read by the post-stream background
    # task. Safe because the stream (and thus the task) only ends after the
    # thread's sentinel.
    recon_pairs: list[tuple[uuid.UUID, str]] = []

    def run_ingestion() -> None:
        db = SessionLocal()
        try:
            result = ingest_grn(
                file_path=tmp_path, org_id=org_id, db=db,
                on_progress=on_progress, replace=replace, period=period,
            )
            recon_pairs.extend(_recon_pairs(db, org_id, result.affected_periods))
            progress_queue.put({
                "type": "result",
                "status": result.status,
                "rows_ingested": result.rows_ingested,
                "rows_skipped": result.rows_skipped,
                "rows_duplicate": result.rows_duplicate,
                "rows_replaced": result.rows_replaced,
                "suppliers_created": result.suppliers_created,
                "suppliers_existing": result.suppliers_existing,
                "errors": result.errors,
                "period": result.period,
                "detected_period": result.detected_period,
                "period_mismatch_pct": result.period_mismatch_pct,
                "period_warning": result.period_warning,
            })
        except Exception:
            logger.exception("GRN ingestion failed for org=%s", org_id)
            progress_queue.put({
                "type": "result",
                "status": "error",
                "errors": ["Ingestion failed while processing the uploaded file"],
            })
        finally:
            db.close()
            progress_queue.put(None)  # sentinel

    thread = threading.Thread(target=run_ingestion, daemon=True)
    thread.start()

    def event_stream():
        while True:
            item = progress_queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    background_tasks.add_task(_run_auto_recon, recon_pairs)
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", background=background_tasks
    )
