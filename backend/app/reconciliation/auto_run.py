"""Background auto-reconciliation triggered by data uploads.

Reconciliation is no longer a user-facing action: statement and GRN uploads
schedule it via FastAPI BackgroundTasks and the mismatch page shows the
latest results. Manual runs remain available for engine testing via
`scripts/run_recon.py` (and the hidden /reconciliation page).
"""
from __future__ import annotations

import logging
import uuid

from app.db import SessionLocal
from app.reconciliation.orchestrator import run_reconciliation

logger = logging.getLogger(__name__)


async def auto_reconcile(supplier_id: uuid.UUID, period: str) -> None:
    """Run reconciliation for one supplier+period with its own DB session.

    Designed for BackgroundTasks: never raises — a failed auto-run logs and
    leaves the previous run's results in place.
    """
    db = SessionLocal()
    try:
        run = await run_reconciliation(supplier_id, period, db)
        logger.info(
            "Auto-reconciliation completed: supplier=%s period=%s run=%s "
            "(matched=%s, discrepancies=%s)",
            supplier_id, period, run.id, run.matched_count, run.discrepancy_count,
        )
    except Exception:
        logger.exception(
            "Auto-reconciliation failed: supplier=%s period=%s", supplier_id, period
        )
    finally:
        db.close()
