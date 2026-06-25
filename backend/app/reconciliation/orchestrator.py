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
from app.reconciliation.multi_delivery import run_multi_delivery_match

logger = logging.getLogger(__name__)


def _split_by_balance(
    erp_candidates: list[MatchCandidate],
    stmt_items: list[StatementItem],
) -> tuple[
    list[MatchCandidate], list[StatementItem],  # balanced (for 1:1 matching)
    list[MatchCandidate], list[StatementItem],  # imbalanced (for aggregation: Layer 3 then fallback)
]:
    """Pre-split items into balanced and imbalanced groups.

    Checks at PO+PN (composite key) level, not just PO level. This catches
    cases where a PO looks balanced overall but a specific part number has
    many more statement lines than ERP records (supplier records individual
    deliveries, ERP consolidates into fewer GRN receipts).

    Balanced: stmt line count <= ERP record count for the PO+PN → 1:1 matching
    Imbalanced: stmt line count > ERP record count → aggregation (Layer 3 first,
    then the aggregate fallback)
    """
    # Group by PO+PN composite key
    erp_by_key: dict[tuple[str, str], list[MatchCandidate]] = defaultdict(list)
    for e in erp_candidates:
        po = normalize_po_number(e.po_number)
        pn = (e.material_number or "").strip()
        if po and pn:
            erp_by_key[(po, pn)].append(e)
        elif po:
            erp_by_key[(po, "")].append(e)

    stmt_by_key: dict[tuple[str, str], list[StatementItem]] = defaultdict(list)
    for s in stmt_items:
        po = normalize_po_number(s.po_number)
        pn = (s.material_number or "").strip()
        if po and pn:
            stmt_by_key[(po, pn)].append(s)
        elif po:
            stmt_by_key[(po, "")].append(s)

    # Detect imbalanced PO+PN groups where statement has more lines than ERP
    IMBALANCE_THRESHOLD = 1.4
    imbalanced_keys: set[tuple[str, str]] = set()
    for key in stmt_by_key:
        stmt_count = len(stmt_by_key[key])
        erp_count = len(erp_by_key.get(key, []))
        if erp_count > 0 and stmt_count > erp_count * IMBALANCE_THRESHOLD:
            imbalanced_keys.add(key)

    # Build sets of IDs to route to aggregate
    imbalanced_erp_ids: set = set()
    imbalanced_stmt_ids: set = set()
    for key in imbalanced_keys:
        for e in erp_by_key.get(key, []):
            imbalanced_erp_ids.add(e.erp_id)
        for s in stmt_by_key.get(key, []):
            imbalanced_stmt_ids.add(s.line_id)

    balanced_erp = [e for e in erp_candidates if e.erp_id not in imbalanced_erp_ids]
    imbalanced_erp = [e for e in erp_candidates if e.erp_id in imbalanced_erp_ids]
    balanced_stmt = [s for s in stmt_items if s.line_id not in imbalanced_stmt_ids]
    imbalanced_stmt = [s for s in stmt_items if s.line_id in imbalanced_stmt_ids]

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


# --- Review-queue classification --------------------------------------------
#
# Nothing auto-matches. Every matched pair is queued for human review
# (status="pending_review"); items with no match are flagged "unmatched".
# Each result is scored and assigned a sort_priority so the review UI can show
# the highest-confidence work first (1 = highest, 6 = no match).

REVIEW_PENDING = "pending_review"
REVIEW_UNMATCHED = "unmatched"

# review match_type -> (confidence_score, confidence_label, sort_priority).
# AI overrides the score with the model's own confidence (label/priority fixed).
# Layer 2.5 "aggregate" and Layer 3 "multi_delivery" share the "Aggregated Match"
# bucket (sort_priority 4) per the review spec. "multi_po_dn" is retained so any
# historical rows from the previous Layer 3 still classify into the same bucket.
_REVIEW_META: dict[str, tuple[int, str, int]] = {
    "exact": (100, "Exact Match", 1),
    "near_exact": (92, "High Confidence — Small Discrepancy", 2),
    "fuzzy": (75, "Probable Match", 3),
    "aggregate": (70, "Aggregated Match", 4),
    "multi_delivery": (70, "Aggregated Match", 4),
    "multi_po_dn": (70, "Aggregated Match", 4),
    "ai": (0, "AI Suggested — Careful Review", 5),
    "unmatched": (0, "No Match Found", 6),
}

# Default for any unexpected match_type — treat as careful-review AI tier.
_REVIEW_FALLBACK = (0, "AI Suggested — Careful Review", 5)

# Spec band for the "Small Discrepancy" / score-92 bucket: both deltas <= 0.5%.
NEAR_EXACT_TOLERANCE_PCT = 0.5


def _pct(delta: Decimal | None, base: Decimal | None) -> float:
    """Percentage magnitude of delta relative to the ERP base. 0 if base is 0/None."""
    if not base or delta is None:
        return 0.0
    try:
        return float(abs(delta) / abs(base) * 100)
    except (ZeroDivisionError, ArithmeticError):
        return 0.0


def _discrepancy_note(match: MatchResult, in_tolerance: bool) -> str:
    """Inline discrepancy note shown to the accountant for an exact-key match.

    Uses the exact spec wording for the in-tolerance (<=0.5%) case; a distinct
    wording for larger deltas so a material discrepancy is never described as
    "small / likely rounding".
    """
    erp, stmt = match.erp, match.statement
    qty_delta = match.quantity_delta if match.quantity_delta is not None else Decimal("0")
    price_delta = match.price_delta if match.price_delta is not None else Decimal("0")
    qty_pct = _pct(qty_delta, erp.quantity)
    price_pct = _pct(price_delta, erp.po_price)
    body = (
        f"Quantity: ERP {erp.quantity} vs Supplier {stmt.quantity} "
        f"(delta: {qty_delta} units, {qty_pct:.2f}%). "
        f"Price: ERP {erp.po_price} vs Supplier {stmt.unit_price} "
        f"(delta: {float(price_delta):.4f}, {price_pct:.2f}%). "
    )
    if in_tolerance:
        return (
            "Small discrepancy detected. " + body
            + "Likely rounding or minor data entry difference — confirm with supplier."
        )
    return (
        "Discrepancy detected. " + body
        + "Exceeds the 0.5% tolerance — review carefully before confirming."
    )


def _classify_review(match: MatchResult) -> dict[str, Any]:
    """Map a matched MatchResult to its review-queue fields.

    Splits Layer-1 'exact' matches into 'exact' (deltas exactly zero) vs
    'near_exact' (any nonzero qty/price delta). Within near_exact, deltas inside
    the 0.5% band keep the "Small Discrepancy" label/score 92; larger deltas stay
    in the same priority-2 attention queue but are labelled accurately with a
    lower score (never auto-confirmable). All other layers keep their match_type
    and are queued for review unchanged.
    """
    review_type = match.match_type
    in_tolerance = True
    if review_type == "exact":
        qd = match.quantity_delta if match.quantity_delta is not None else Decimal("0")
        pd = match.price_delta if match.price_delta is not None else Decimal("0")
        if qd != 0 or pd != 0:
            review_type = "near_exact"
            in_tolerance = (
                _pct(qd, match.erp.quantity) <= NEAR_EXACT_TOLERANCE_PCT
                and _pct(pd, match.erp.po_price) <= NEAR_EXACT_TOLERANCE_PCT
            )

    score, label, priority = _REVIEW_META.get(review_type, _REVIEW_FALLBACK)

    # AI score comes from the model's own confidence (0-1 -> 0-100).
    if review_type == "ai" and match.confidence is not None:
        score = max(0, min(100, round(float(match.confidence) * 100)))

    note: str | None = None
    if review_type == "near_exact":
        note = _discrepancy_note(match, in_tolerance)
        if not in_tolerance:
            score, label = 80, "High Confidence — Discrepancy"

    return {
        "match_type": review_type,
        "status": REVIEW_PENDING,
        "confidence_score": score,
        "confidence_label": label,
        "sort_priority": priority,
        "discrepancy_note": note,
    }


def _line_amount(match: MatchResult) -> float:
    """Transaction amount used to sort the review queue (largest value first).

    Prefers the supplier statement amount, falling back to the ERP amount.
    """
    amt = match.statement.amount if match.statement.amount is not None else match.erp.amount
    return float(amt) if amt is not None else 0.0


def _match_to_result(
    match: MatchResult,
    run_id: Any,
    supplier_id: Any,
    period: str,
) -> ReconciliationResult:
    review = _classify_review(match)
    details = {**(match.match_details or {}), "amount": _line_amount(match)}
    return ReconciliationResult(
        run_id=run_id,
        supplier_id=supplier_id,
        period=period,
        erp_record_id=match.erp.erp_id,
        statement_line_id=match.statement.line_id,
        match_type=review["match_type"],
        quantity_delta=match.quantity_delta,
        price_delta=match.price_delta,
        amount_delta=match.amount_delta,
        discrepancy_type=match.discrepancy_type,
        confidence=match.confidence,
        status=review["status"],
        confidence_score=review["confidence_score"],
        confidence_label=review["confidence_label"],
        sort_priority=review["sort_priority"],
        discrepancy_note=review["discrepancy_note"],
        # A layer may pre-populate a resolution_note (e.g. Layer 3 marks a group
        # with "price inconsistency across deliveries"); carry it through.
        resolution_note=details.get("resolution_note"),
        match_details=details,
    )


def _period_date_range(period: str) -> tuple[datetime, datetime]:
    """Convert 'YYYY-MM' period to (first_day, last_day) datetime range.

    No longer used to filter ERP rows (those are scoped by the explicit period
    tag now), but kept as a utility for the period's calendar bounds.
    """
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

    Waterfall: Layer 1 (exact) → Layer 2 (fuzzy) → Layer 3 (multi-delivery aggregation) → Layer 4 (AI).
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
        # Load ERP records for supplier+period. ERP rows are stamped with the
        # accounting period at ingest time, so we match the period tag directly
        # (consistent with how supplier statements are scoped below).
        logger.info(
            "[RECON DEBUG] Starting reconciliation: supplier_id=%s, period=%s",
            supplier_id, period,
        )

        erp_records = (
            db.query(ERPRecord)
            .filter(
                ERPRecord.supplier_id == supplier_id,
                ERPRecord.period == period,
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
        erp_pos = {normalize_po_number(e.po_number) for e in erp_candidates} - {None}
        stmt_pos = {normalize_po_number(s.po_number) for s in stmt_items if s.po_number} - {None}
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
        # records) directly to aggregation (Layer 3 first) instead of 1:1 matching.
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

        # Layer 3: Multi-delivery aggregation — runs FIRST so the discrepancy-aware
        # layer adjudicates every (po_number, material_number) group (summing each
        # side, checking qty + amount within tolerance, guarding ERP price drift)
        # before the always-"matched" aggregate fallback can mask it. Receives the
        # imbalanced PO groups plus anything L1/L2 left unmatched.
        l3_input_erp = imbalanced_erp + unmatched_erp
        l3_input_stmt = imbalanced_stmt + unmatched_stmt
        logger.info(
            "[RECON DEBUG] Layer 3 input: %d ERP (%d imbalanced + %d L2 leftover), "
            "%d stmt (%d imbalanced + %d L2 leftover)",
            len(l3_input_erp), len(imbalanced_erp), len(unmatched_erp),
            len(l3_input_stmt), len(imbalanced_stmt), len(unmatched_stmt),
        )
        l3_matches, unmatched_erp, unmatched_stmt = run_multi_delivery_match(
            l3_input_erp, l3_input_stmt, qty_tol, price_tol
        )
        logger.info(
            "[RECON DEBUG] Layer 3 (multi-delivery aggregation): %d matches, "
            "%d ERP unmatched, %d stmt unmatched",
            len(l3_matches), len(unmatched_erp), len(unmatched_stmt),
        )
        for m in l3_matches:
            all_results.append(_match_to_result(m, run.id, supplier_id, period))

        # Layer 3.5: Aggregate fallback — mops up what Layer 3 could not group on a
        # strict (po, material) key, chiefly PO-level cross-material reconciliation
        # (ERP and supplier using different material codes for the same parts). Runs
        # on Layer 3's leftovers.
        l25_matches, unmatched_erp, unmatched_stmt = run_aggregate_match(
            unmatched_erp, unmatched_stmt, qty_tol, price_tol
        )
        logger.info(
            "[RECON DEBUG] Layer 3.5 (aggregate fallback): %d matches, "
            "%d ERP unmatched, %d stmt unmatched",
            len(l25_matches), len(unmatched_erp), len(unmatched_stmt),
        )
        for m in l25_matches:
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
                status=REVIEW_UNMATCHED,
                discrepancy_type="missing_from_statement",
                confidence_score=0,
                confidence_label="No Match Found",
                sort_priority=6,
                match_details={
                    "layer": "unmatched",
                    "side": "erp",
                    "amount": float(erp.amount) if erp.amount is not None else 0.0,
                },
            ))

        # Create unmatched results for remaining statement items
        for stmt in unmatched_stmt:
            all_results.append(ReconciliationResult(
                run_id=run.id,
                supplier_id=supplier_id,
                period=period,
                statement_line_id=stmt.line_id,
                match_type="unmatched",
                status=REVIEW_UNMATCHED,
                discrepancy_type="missing_from_erp",
                confidence_score=0,
                confidence_label="No Match Found",
                sort_priority=6,
                match_details={
                    "layer": "unmatched",
                    "side": "statement",
                    "amount": float(stmt.amount) if stmt.amount is not None else 0.0,
                },
            ))

        # Final summary
        logger.info(
            "[RECON DEBUG] === FINAL SUMMARY ===\n"
            "  Total results: %d\n"
            "  Unmatched ERP (missing from statement): %d\n"
            "  Unmatched stmt (missing from ERP): %d\n"
            "  Layer breakdown: L1=%d, L2=%d, L3=%d, L3.5=%d, L4=%d",
            len(all_results),
            len(unmatched_erp), len(unmatched_stmt),
            len(l1_matches), len(l2_matches), len(l3_matches),
            len(l25_matches),
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

        # Update run stats. Nothing auto-matches now, so "matched" means a pair
        # was found and queued for review; "discrepancy" means that pair (or an
        # unmatched leftover) carries a discrepancy_type worth flagging.
        matched = sum(1 for r in all_results if r.match_type != "unmatched")
        discrepancy = sum(1 for r in all_results if r.discrepancy_type is not None)
        unmatched = sum(1 for r in all_results if r.match_type == "unmatched")

        # Match rate is statement-centric: how well can we verify the supplier's
        # claims against ERP? ERP-only items (not in statement) are informational
        # and don't drag down the rate.
        stmt_matched = sum(
            1 for r in all_results
            if r.match_type != "unmatched" and r.statement_line_id is not None
        )
        stmt_total = run.total_statement  # total statement line items
        unmatched_erp_count = sum(
            1 for r in all_results
            if r.match_type == "unmatched" and r.discrepancy_type == "missing_from_statement"
        )

        run.matched_count = matched
        run.discrepancy_count = discrepancy
        run.unmatched_count = unmatched
        run.auto_match_rate = (
            Decimal(str(round(stmt_matched / stmt_total * 100, 2)))
            if stmt_total and stmt_total > 0 else Decimal("0")
        )

        logger.info(
            "[RECON DEBUG] Match rate: %d/%d statement items matched (%.1f%%). "
            "%d ERP items not in statement (informational).",
            stmt_matched, stmt_total,
            float(run.auto_match_rate),
            unmatched_erp_count,
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
