"""Reconciliation orchestrator — waterfall executor for the 4-layer matching engine.

Loads ERP + statement data → runs layers 1-4 → bulk inserts results → updates run stats.
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    ERPRecord,
    ReconciliationConfig,
    ReconciliationResult,
    ReconciliationRun,
    StatementLineItem,
    Supplier,
    SupplierStatement,
)
from app.reconciliation.ai_match import run_ai_match
from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    run_exact_match,
)
from app.reconciliation.fuzzy_match import run_fuzzy_match
from app.reconciliation.multi_po_dn import run_multi_po_dn_match

logger = logging.getLogger(__name__)


def _load_config(db: Session, org_id: Any) -> dict[str, Any]:
    """Load reconciliation config for org, or return defaults."""
    config = (
        db.query(ReconciliationConfig)
        .filter(ReconciliationConfig.org_id == org_id)
        .first()
    )
    if config:
        return {
            "qty_tolerance_pct": float(config.qty_tolerance_pct),
            "price_tolerance_pct": float(config.price_tolerance_pct),
            "auto_resolve_exact": config.auto_resolve_exact,
            "ai_layer_enabled": config.ai_layer_enabled,
            "ai_max_tokens_per_run": config.ai_max_tokens_per_run,
        }
    return {
        "qty_tolerance_pct": 0.50,
        "price_tolerance_pct": 0.50,
        "auto_resolve_exact": True,
        "ai_layer_enabled": True,
        "ai_max_tokens_per_run": 10000,
    }


def _erp_to_candidate(record: ERPRecord) -> MatchCandidate:
    return MatchCandidate(
        erp_id=record.id,
        po_number=record.po_number,
        material_number=record.material_number,
        quantity=record.quantity,
        po_price=record.po_price,
        amount=record.amount,
        grn_date=record.grn_date,
        delivery_note=record.delivery_note,
    )


def _stmt_to_item(line: StatementLineItem) -> StatementItem:
    return StatementItem(
        line_id=line.id,
        po_number=line.po_number,
        material_number=line.material_number,
        quantity=line.quantity,
        unit_price=line.unit_price,
        amount=line.amount,
        delivery_date=line.delivery_date,
        delivery_note_ref=line.delivery_note_ref,
    )


def _match_to_result(
    match: MatchResult,
    run_id: Any,
    supplier_id: Any,
    period: str,
) -> ReconciliationResult:
    return ReconciliationResult(
        run_id=run_id,
        supplier_id=supplier_id,
        period=period,
        erp_record_id=match.erp.erp_id,
        statement_line_id=match.statement.line_id,
        match_type=match.match_type,
        quantity_delta=match.quantity_delta,
        price_delta=match.price_delta,
        amount_delta=match.amount_delta,
        discrepancy_type=match.discrepancy_type,
        confidence=match.confidence,
        status=match.status,
        match_details=match.match_details,
    )


def _period_date_range(period: str) -> tuple[datetime, datetime]:
    """Convert 'YYYY-MM' period to (first_day, last_day) datetime range."""
    year, month = int(period[:4]), int(period[5:7])
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end


async def run_reconciliation(
    supplier_id: Any,
    period: str,
    db: Session,
) -> ReconciliationRun:
    """Execute reconciliation for a supplier+period.

    Waterfall: Layer 1 (exact) → Layer 2 (fuzzy) → Layer 3 (DN aggregation) → Layer 4 (AI).
    """
    # Verify supplier exists
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise ValueError(f"Supplier {supplier_id} not found")

    # Load config
    config = _load_config(db, supplier.org_id)
    qty_tol = Decimal(str(config["qty_tolerance_pct"]))
    price_tol = Decimal(str(config["price_tolerance_pct"]))

    # Create run record
    run = ReconciliationRun(
        supplier_id=supplier_id,
        period=period,
        status="running",
        config=config,
    )
    db.add(run)
    db.flush()

    try:
        # Load ERP records for supplier+period
        period_start, period_end = _period_date_range(period)
        erp_records = (
            db.query(ERPRecord)
            .filter(
                ERPRecord.supplier_id == supplier_id,
                ERPRecord.grn_date >= period_start,
                ERPRecord.grn_date <= period_end,
            )
            .all()
        )

        # Load statement line items for supplier+period
        statements = (
            db.query(SupplierStatement)
            .filter(
                SupplierStatement.supplier_id == supplier_id,
                SupplierStatement.period == period,
            )
            .all()
        )
        stmt_lines = []
        for stmt in statements:
            stmt_lines.extend(
                db.query(StatementLineItem)
                .filter(StatementLineItem.statement_id == stmt.id)
                .all()
            )

        erp_candidates = [_erp_to_candidate(r) for r in erp_records]
        stmt_items = [_stmt_to_item(l) for l in stmt_lines]

        run.total_erp = len(erp_candidates)
        run.total_statement = len(stmt_items)

        all_results: list[ReconciliationResult] = []

        # Layer 1: Exact match
        l1_matches, unmatched_erp, unmatched_stmt = run_exact_match(
            erp_candidates, stmt_items, qty_tol, price_tol
        )
        for m in l1_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 2: Fuzzy match
        l2_matches, unmatched_erp, unmatched_stmt = run_fuzzy_match(
            unmatched_erp, unmatched_stmt, qty_tol, price_tol
        )
        for m in l2_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 3: Multi-PO delivery note aggregation
        l3_matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(
            unmatched_erp, unmatched_stmt, qty_tol, price_tol
        )
        for m in l3_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 4: AI match (if enabled)
        if config["ai_layer_enabled"]:
            l4_matches, unmatched_erp, unmatched_stmt = await run_ai_match(
                unmatched_erp,
                unmatched_stmt,
                qty_tol,
                price_tol,
                anthropic_api_key=settings.anthropic_api_key,
                max_tokens=config["ai_max_tokens_per_run"],
            )
            for m in l4_matches:
                all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Create unmatched results for remaining ERP records
        for erp in unmatched_erp:
            all_results.append(ReconciliationResult(
                run_id=run.id,
                supplier_id=supplier_id,
                period=period,
                erp_record_id=erp.erp_id,
                match_type="unmatched",
                status="discrepancy",
                discrepancy_type="missing_from_statement",
                match_details={"layer": "unmatched", "side": "erp"},
            ))

        # Create unmatched results for remaining statement items
        for stmt in unmatched_stmt:
            all_results.append(ReconciliationResult(
                run_id=run.id,
                supplier_id=supplier_id,
                period=period,
                statement_line_id=stmt.line_id,
                match_type="unmatched",
                status="discrepancy",
                discrepancy_type="missing_from_erp",
                match_details={"layer": "unmatched", "side": "statement"},
            ))

        # Bulk insert results
        db.add_all(all_results)

        # Update run stats
        matched = sum(1 for r in all_results if r.status == "matched")
        discrepancy = sum(1 for r in all_results if r.status == "discrepancy")
        unmatched = sum(1 for r in all_results if r.match_type == "unmatched")
        total = len(all_results)

        run.matched_count = matched
        run.discrepancy_count = discrepancy
        run.unmatched_count = unmatched
        run.auto_match_rate = (
            Decimal(str(round(matched / total * 100, 2))) if total > 0 else Decimal("0")
        )
        run.status = "completed"
        run.completed_at = datetime.utcnow()

        db.commit()
        db.refresh(run)
        return run

    except Exception as e:
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        db.commit()
        logger.exception("Reconciliation run failed: %s", e)
        raise
