"""Reconciliation orchestrator — waterfall executor for the 4-layer matching engine.

Loads ERP + statement data → runs layers 1-4 → bulk inserts results → updates run stats.
"""
from __future__ import annotations

import calendar
import logging
from collections import defaultdict
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
from app.ingestion.cleaning import normalize_po_number
from app.reconciliation.aggregate_match import run_aggregate_match
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


def _split_by_balance(
    erp_candidates: list[MatchCandidate],
    stmt_items: list[StatementItem],
) -> tuple[
    list[MatchCandidate], list[StatementItem],  # balanced (for 1:1 matching)
    list[MatchCandidate], list[StatementItem],  # imbalanced (for aggregate matching)
]:
    """Pre-split items into balanced and imbalanced PO groups.

    Balanced: stmt line count <= ERP record count for the PO → suitable for 1:1 matching
    Imbalanced: stmt line count > ERP record count → supplier has more granular line
    items than ERP (consolidation pattern), so aggregate matching should handle these.
    """
    erp_by_po: dict[str, list[MatchCandidate]] = defaultdict(list)
    for e in erp_candidates:
        po = normalize_po_number(e.po_number)
        if po:
            erp_by_po[po].append(e)

    stmt_by_po: dict[str, list[StatementItem]] = defaultdict(list)
    for s in stmt_items:
        po = normalize_po_number(s.po_number)
        if po:
            stmt_by_po[po].append(s)

    # Only defer PO groups where the statement has significantly more lines
    # than ERP (1.4x+). Slightly imbalanced groups work better with 1:1 matching
    # since the extra lines are just cross-month spillover.
    IMBALANCE_THRESHOLD = 1.4
    imbalanced_pos: set[str] = set()
    for po in stmt_by_po:
        stmt_count = len(stmt_by_po[po])
        erp_count = len(erp_by_po.get(po, []))
        if erp_count > 0 and stmt_count > erp_count * IMBALANCE_THRESHOLD:
            imbalanced_pos.add(po)

    # Split ERP
    balanced_erp = []
    imbalanced_erp = []
    for e in erp_candidates:
        po = normalize_po_number(e.po_number)
        if po in imbalanced_pos:
            imbalanced_erp.append(e)
        else:
            balanced_erp.append(e)

    # Split stmt
    balanced_stmt = []
    imbalanced_stmt = []
    for s in stmt_items:
        po = normalize_po_number(s.po_number)
        if po in imbalanced_pos:
            imbalanced_stmt.append(s)
        else:
            balanced_stmt.append(s)

    return balanced_erp, balanced_stmt, imbalanced_erp, imbalanced_stmt


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
        logger.info(
            "[RECON DEBUG] Starting reconciliation: supplier_id=%s, period=%s, "
            "date_range=%s to %s",
            supplier_id, period, period_start, period_end,
        )

        erp_records = (
            db.query(ERPRecord)
            .filter(
                ERPRecord.supplier_id == supplier_id,
                ERPRecord.grn_date >= period_start,
                ERPRecord.grn_date <= period_end,
            )
            .all()
        )
        logger.info(
            "[RECON DEBUG] Loaded %d ERP records for supplier %s in period %s",
            len(erp_records), supplier_id, period,
        )
        if not erp_records:
            # Check if there are ANY ERP records for this supplier (period mismatch?)
            all_erp_count = db.query(ERPRecord).filter(
                ERPRecord.supplier_id == supplier_id
            ).count()
            if all_erp_count > 0:
                # Find the actual date range of existing records
                from sqlalchemy import func as sqlfunc
                date_range = db.query(
                    sqlfunc.min(ERPRecord.grn_date),
                    sqlfunc.max(ERPRecord.grn_date),
                ).filter(ERPRecord.supplier_id == supplier_id).first()
                logger.warning(
                    "[RECON DEBUG] ⚠️ PERIOD MISMATCH: Supplier has %d ERP records "
                    "but NONE in period %s. Their GRN dates span %s to %s. "
                    "Check if you're using the correct period.",
                    all_erp_count, period, date_range[0], date_range[1],
                )
            else:
                logger.warning(
                    "[RECON DEBUG] ⚠️ NO ERP DATA: Supplier %s has zero ERP records. "
                    "Upload GRN data first via /api/v1/erp/upload.",
                    supplier_id,
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
        logger.info(
            "[RECON DEBUG] Found %d statement(s) for supplier %s, period %s",
            len(statements), supplier_id, period,
        )
        stmt_lines = []
        for stmt in statements:
            lines = (
                db.query(StatementLineItem)
                .filter(StatementLineItem.statement_id == stmt.id)
                .all()
            )
            logger.info(
                "[RECON DEBUG]   Statement %s: %d line items", stmt.id, len(lines),
            )
            stmt_lines.extend(lines)

        if not stmt_lines:
            all_stmts = db.query(SupplierStatement).filter(
                SupplierStatement.supplier_id == supplier_id
            ).all()
            if all_stmts:
                periods = [s.period for s in all_stmts]
                logger.warning(
                    "[RECON DEBUG] ⚠️ NO STATEMENT LINES for period %s. "
                    "Supplier has statements for periods: %s",
                    period, periods,
                )
            else:
                logger.warning(
                    "[RECON DEBUG] ⚠️ NO STATEMENTS: Supplier %s has no uploaded "
                    "statements at all. Upload via /api/v1/statements/upload.",
                    supplier_id,
                )

        erp_candidates = [_erp_to_candidate(r) for r in erp_records]
        stmt_items = [_stmt_to_item(l) for l in stmt_lines]

        run.total_erp = len(erp_candidates)
        run.total_statement = len(stmt_items)

        # Log sample PO numbers from each side to check alignment
        erp_pos = set(normalize_po_number(e.po_number) for e in erp_candidates)
        stmt_pos = set(normalize_po_number(s.po_number) for s in stmt_items if s.po_number)
        common_pos = erp_pos & stmt_pos
        logger.info(
            "[RECON DEBUG] PO overlap: %d ERP POs, %d statement POs, %d in common (%.0f%% overlap)",
            len(erp_pos), len(stmt_pos), len(common_pos),
            (len(common_pos) / len(stmt_pos) * 100) if stmt_pos else 0,
        )
        if stmt_pos and not common_pos:
            logger.warning(
                "[RECON DEBUG] ⚠️ ZERO PO OVERLAP! ERP POs (sample): %s | "
                "Statement POs (sample): %s — likely wrong supplier or wrong file!",
                sorted(erp_pos)[:5], sorted(stmt_pos)[:5],
            )
        elif common_pos and len(common_pos) < len(stmt_pos):
            only_in_stmt = stmt_pos - erp_pos
            logger.info(
                "[RECON DEBUG] POs only in statement (no ERP match, sample): %s",
                sorted(only_in_stmt)[:5],
            )

        all_results: list[ReconciliationResult] = []

        # Pre-split: route imbalanced PO groups (more stmt lines than ERP
        # records) directly to aggregate matching instead of 1:1 matching.
        balanced_erp, balanced_stmt, imbalanced_erp, imbalanced_stmt = (
            _split_by_balance(erp_candidates, stmt_items)
        )
        logger.info(
            "[RECON DEBUG] Pre-split: balanced=%d ERP + %d stmt, "
            "imbalanced=%d ERP + %d stmt (routed to aggregate)",
            len(balanced_erp), len(balanced_stmt),
            len(imbalanced_erp), len(imbalanced_stmt),
        )

        # Layer 1: Exact match (balanced groups only)
        l1_matches, unmatched_erp, unmatched_stmt = run_exact_match(
            balanced_erp, balanced_stmt, qty_tol, price_tol
        )
        l1_matched = sum(1 for m in l1_matches if m.status == "matched")
        l1_disc = sum(1 for m in l1_matches if m.status == "discrepancy")
        logger.info(
            "[RECON DEBUG] Layer 1 (exact): %d matches (%d clean, %d discrepancy), "
            "%d ERP unmatched, %d stmt unmatched",
            len(l1_matches), l1_matched, l1_disc,
            len(unmatched_erp), len(unmatched_stmt),
        )
        for m in l1_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 2: Fuzzy match (balanced groups only)
        l2_matches, unmatched_erp, unmatched_stmt = run_fuzzy_match(
            unmatched_erp, unmatched_stmt, qty_tol, price_tol
        )
        l2_matched = sum(1 for m in l2_matches if m.status == "matched")
        l2_disc = sum(1 for m in l2_matches if m.status == "discrepancy")
        logger.info(
            "[RECON DEBUG] Layer 2 (fuzzy): %d matches (%d clean, %d discrepancy), "
            "%d ERP unmatched, %d stmt unmatched",
            len(l2_matches), l2_matched, l2_disc,
            len(unmatched_erp), len(unmatched_stmt),
        )
        for m in l2_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 2.5: Aggregate match — handles imbalanced PO groups plus
        # any remaining unmatched from L1/L2
        aggregate_erp = imbalanced_erp + unmatched_erp
        aggregate_stmt = imbalanced_stmt + unmatched_stmt
        logger.info(
            "[RECON DEBUG] Layer 2.5 input: %d ERP (%d imbalanced + %d L2 leftover), "
            "%d stmt (%d imbalanced + %d L2 leftover)",
            len(aggregate_erp), len(imbalanced_erp), len(unmatched_erp),
            len(aggregate_stmt), len(imbalanced_stmt), len(unmatched_stmt),
        )
        l25_matches, unmatched_erp, unmatched_stmt = run_aggregate_match(
            aggregate_erp, aggregate_stmt, qty_tol, price_tol
        )
        logger.info(
            "[RECON DEBUG] Layer 2.5 (aggregate): %d matches, "
            "%d ERP unmatched, %d stmt unmatched",
            len(l25_matches), len(unmatched_erp), len(unmatched_stmt),
        )
        for m in l25_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 3: Multi-PO delivery note aggregation
        l3_matches, unmatched_erp, unmatched_stmt = run_multi_po_dn_match(
            unmatched_erp, unmatched_stmt, qty_tol, price_tol
        )
        logger.info(
            "[RECON DEBUG] Layer 3 (DN aggregation): %d matches, "
            "%d ERP unmatched, %d stmt unmatched",
            len(l3_matches), len(unmatched_erp), len(unmatched_stmt),
        )
        for m in l3_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 4: AI match (if enabled)
        l4_matches = []
        if config["ai_layer_enabled"]:
            logger.info(
                "[RECON DEBUG] Layer 4 (AI): sending %d ERP + %d stmt to Claude",
                len(unmatched_erp), len(unmatched_stmt),
            )
            l4_matches, unmatched_erp, unmatched_stmt = await run_ai_match(
                unmatched_erp,
                unmatched_stmt,
                qty_tol,
                price_tol,
                anthropic_api_key=settings.anthropic_api_key,
                max_tokens=config["ai_max_tokens_per_run"],
            )
            logger.info(
                "[RECON DEBUG] Layer 4 (AI): %d matches, "
                "%d ERP still unmatched, %d stmt still unmatched",
                len(l4_matches), len(unmatched_erp), len(unmatched_stmt),
            )
            for m in l4_matches:
                all_results.append(_match_to_result(m, run.id, supplier_id, period))
        else:
            logger.info("[RECON DEBUG] Layer 4 (AI) disabled by config")

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

        # Final summary
        logger.info(
            "[RECON DEBUG] === FINAL SUMMARY ===\n"
            "  Total results: %d\n"
            "  Unmatched ERP (missing from statement): %d\n"
            "  Unmatched stmt (missing from ERP): %d\n"
            "  Layer breakdown: L1=%d, L2=%d, L2.5=%d, L3=%d, L4=%d",
            len(all_results),
            len(unmatched_erp), len(unmatched_stmt),
            len(l1_matches), len(l2_matches), len(l25_matches),
            len(l3_matches),
            len(l4_matches),
        )
        if unmatched_erp:
            sample_erp = [(e.po_number, e.material_number, str(e.quantity)) for e in unmatched_erp[:5]]
            logger.info("[RECON DEBUG] Sample unmatched ERP: %s", sample_erp)
        if unmatched_stmt:
            sample_stmt = [(s.po_number, s.material_number, str(s.quantity)) for s in unmatched_stmt[:5]]
            logger.info("[RECON DEBUG] Sample unmatched stmt: %s", sample_stmt)

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
