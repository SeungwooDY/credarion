"""API endpoints for SGWERP GRN (Goods Receipt Note) ingestion."""
from __future__ import annotations

import json
import logging
import queue
import shutil
import tempfile
import threading
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import authorize_org, get_current_user
from app.db import SessionLocal, get_db
from app.ingestion.grn_ingestor import GRNIngestionResult, ingest_grn
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/erp", tags=["erp"])


class GRNIngestionResponse(BaseModel):
    status: str
    rows_ingested: int = 0
    rows_skipped: int = 0
    rows_duplicate: int = 0
    suppliers_created: int = 0
    suppliers_existing: int = 0
    errors: list[str] = []


@router.post("/upload", response_model=GRNIngestionResponse, status_code=201)
def upload_grn(
    file: UploadFile = File(...),
    org_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GRNIngestionResponse:
    """Upload an SGWERP GRN export file for ingestion.

    Accepts .csv, .xlsx, or .xls files. Automatically maps columns,
    upserts suppliers, normalizes data, and inserts erp_records.
    """
    authorize_org(db, user, org_id)
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
    )

    response = GRNIngestionResponse(
        status=result.status,
        rows_ingested=result.rows_ingested,
        rows_skipped=result.rows_skipped,
        rows_duplicate=result.rows_duplicate,
        suppliers_created=result.suppliers_created,
        suppliers_existing=result.suppliers_existing,
        errors=result.errors,
    )

    if result.status == "error":
        raise HTTPException(status_code=400, detail=response.model_dump())

    return response


@router.post("/upload-stream")
def upload_grn_stream(
    file: UploadFile = File(...),
    org_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Upload GRN with SSE progress events.

    Returns a text/event-stream with progress updates during ingestion.
    Final event contains the full result.
    """
    authorize_org(db, user, org_id)
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

    def run_ingestion() -> None:
        db = SessionLocal()
        try:
            result = ingest_grn(file_path=tmp_path, org_id=org_id, db=db, on_progress=on_progress)
            progress_queue.put({
                "type": "result",
                "status": result.status,
                "rows_ingested": result.rows_ingested,
                "rows_skipped": result.rows_skipped,
                "rows_duplicate": result.rows_duplicate,
                "suppliers_created": result.suppliers_created,
                "suppliers_existing": result.suppliers_existing,
                "errors": result.errors,
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

    return StreamingResponse(event_stream(), media_type="text/event-stream")
