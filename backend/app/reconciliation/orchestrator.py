"""Reconciliation orchestrator — waterfall executor for the strict matching engine.

Loads ERP + statement data, combines identical rows on BOTH sides (see
preaggregate.py), runs the exact then fuzzy 1:1 layers, records the leftovers
as missing/extra discrepancies, and attaches suggest-only AI hints to the
unmatched rows. Bulk inserts results → updates run stats.

Semantics (2026-07-31): a pair requires identical PO, material, and unit
price with dates inside the configured ± window; quantity is the only field
allowed to deviate. Nothing is ever netted at group level — the old
aggregation layers (multi_delivery, aggregate fallback) are gone.
"""
from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    ERPRecord,
    PeriodSignoff,
    ReconciliationConfig,
    ReconciliationResult,
    ReconciliationRun,
    StatementLineItem,
    Supplier,
    SupplierStatement,
)
from app.ingestion.cleaning import normalize_po_number
from app.reconciliation.ai_match import run_ai_suggestions
from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    run_exact_match,
)
from app.reconciliation.fuzzy_match import run_fuzzy_match
from app.reconciliation.preaggregate import combine_erp_records, combine_statement_lines

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
            "date_tolerance_days": config.date_tolerance_days,
            "auto_resolve_exact": config.auto_resolve_exact,
            "ai_layer_enabled": config.ai_layer_enabled,
            "ai_max_tokens_per_run": config.ai_max_tokens_per_run,
        }
    return {
        "qty_tolerance_pct": 0.50,
        "price_tolerance_pct": 0.50,
        "date_tolerance_days": 3,
        "auto_resolve_exact": True,
        "ai_layer_enabled": True,
        "ai_max_tokens_per_run": 10000,
    }


def _load_carryover(
    db: Session, supplier_id: Any, period: str
) -> tuple[list[ERPRecord], dict[Any, str], dict[Any, list[ReconciliationResult]]]:
    """ERP receipts flagged missing_from_statement in PRIOR periods, still
    unresolved. Suppliers often re-include omitted items in the next month's
    statement, so these join the current run as match candidates instead of
    staying dead discrepancies.

    Only the latest completed run per prior period is consulted (reruns
    supersede). Returns (records, origin_period_by_erp_id,
    prior_results_by_erp_id); origin keeps the EARLIEST period an item went
    missing in, prior_results holds every open prior result so a later match
    can close them all.
    """
    prior_runs = (
        db.query(ReconciliationRun)
        .filter(
            ReconciliationRun.supplier_id == supplier_id,
            ReconciliationRun.status == "completed",
            ReconciliationRun.period < period,
        )
        .order_by(ReconciliationRun.started_at.desc())
        .all()
    )
    latest_by_period: dict[str, ReconciliationRun] = {}
    for r in prior_runs:
        latest_by_period.setdefault(r.period, r)
    if not latest_by_period:
        return [], {}, {}

    period_by_run_id = {run.id: p for p, run in latest_by_period.items()}
    prior_results = (
        db.query(ReconciliationResult)
        .filter(
            ReconciliationResult.run_id.in_(list(period_by_run_id)),
            ReconciliationResult.discrepancy_type == "missing_from_statement",
            ReconciliationResult.status == REVIEW_UNMATCHED,
            ReconciliationResult.erp_record_id.isnot(None),
        )
        .all()
    )
    origin: dict[Any, str] = {}
    prior_by_erp: dict[Any, list[ReconciliationResult]] = defaultdict(list)
    for res in prior_results:
        p = period_by_run_id[res.run_id]
        if res.erp_record_id not in origin or p < origin[res.erp_record_id]:
            origin[res.erp_record_id] = p
        prior_by_erp[res.erp_record_id].append(res)
    if not origin:
        return [], {}, {}

    records = db.query(ERPRecord).filter(ERPRecord.id.in_(list(origin))).all()
    return records, origin, prior_by_erp


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
# The retired aggregation types ("multi_delivery", "aggregate", "multi_po_dn")
# survive only in historical DB rows, which are never re-classified — so they
# have no entry here. "ai" likewise: the AI layer is suggest-only now and its
# hints ride on unmatched rows instead of producing results of their own.
_REVIEW_META: dict[str, tuple[int, str, int]] = {
    "exact": (100, "Exact Match", 1),
    "near_exact": (92, "High Confidence — Small Discrepancy", 2),
    "fuzzy": (75, "Probable Match", 3),
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
        f"(delta: {price_delta}, {price_pct:.2f}%). "
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


def _compute_run_stats(all_results: list, total_statement: int | None) -> dict[str, Any]:
    """Run-level stats from the emitted results. Pure function — unit-testable.

    Counting rules (ADR-0001 amendments — prevent double counting):
      - matched_count: DISTINCT statement lines that found a counterpart.
        Aggregation groups can emit several result rows referencing the same
        underlying pairing (or ERP-only constituent rows) — counting distinct
        statement_line_ids keeps the number meaning "supplier lines verified".
      - discrepancy_count: results carrying a discrepancy_type. Aggregation
        layers set discrepancy_type ONLY on the group's primary row, so a
        discrepant group counts once, not once per constituent row.
      - auto_match_rate: two-sided (2026-07-26, accountant feedback). ERP
        receipts missing from the statement are REAL issues, not
        informational — they join the denominator so a supplier who omits
        deliveries can't score 100%:
            matched stmt lines / (total stmt lines + missing-from-statement)
        Defensive 100% cap — distinct counting makes >100% impossible, the
        cap is a belt-and-braces invariant.
    """
    matched_stmt_ids = {
        r.statement_line_id
        for r in all_results
        if r.match_type != "unmatched" and r.statement_line_id is not None
    }
    matched_count = len(matched_stmt_ids)
    discrepancy_count = sum(1 for r in all_results if r.discrepancy_type is not None)
    unmatched_count = sum(1 for r in all_results if r.match_type == "unmatched")
    # Carryover items (match_details.carryover_from) already counted against
    # their origin period's rate — they stay visible as issues but don't
    # re-penalize this period's denominator.
    unmatched_erp_count = sum(
        1 for r in all_results
        if r.match_type == "unmatched"
        and r.discrepancy_type == "missing_from_statement"
        and not (r.match_details or {}).get("carryover_from")
    )
    denominator = (total_statement or 0) + unmatched_erp_count
    if denominator > 0:
        rate = min(Decimal("100"), Decimal(str(round(matched_count / denominator * 100, 2))))
    else:
        rate = Decimal("0")
    return {
        "matched_count": matched_count,
        "discrepancy_count": discrepancy_count,
        "unmatched_count": unmatched_count,
        "unmatched_erp_count": unmatched_erp_count,
        "auto_match_rate": rate,
    }


def _line_amount(match: MatchResult) -> float:
    """Transaction amount used to sort the review queue (largest value first).

    Prefers the supplier statement amount, falling back to the ERP amount.
    Either side may be None for aggregation-group constituent rows.
    """
    amt = None
    if match.statement is not None and match.statement.amount is not None:
        amt = match.statement.amount
    elif match.erp is not None:
        amt = match.erp.amount
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
        erp_record_id=match.erp.erp_id if match.erp is not None else None,
        statement_line_id=match.statement.line_id if match.statement is not None else None,
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
        match_details=details,
    )


def _period_date_range(period: str) -> tuple[datetime, datetime]:
    """Convert 'YYYY-MM' period to (first_day, last_day) datetime range."""
    year, month = int(period[:4]), int(period[5:7])
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end


def _carry_forward_review_state(
    db: Session,
    supplier_id: Any,
    period: str,
    run: ReconciliationRun,
    all_results: list,
) -> None:
    """Copy human review state (discrepancy marks, resolutions) from the
    previous completed run onto equivalent rows of the new run.

    Every run rebuilds its result rows from scratch, which used to silently
    drop marks and resolves whenever reconciliation re-ran (now automatic on
    every upload). A row is "equivalent" when it references the same ERP
    record + statement line with the same discrepancy_type and unchanged
    qty/price deltas — if the underlying data shifted, the old judgement may
    no longer apply and is deliberately NOT carried.
    """
    prev_run = (
        db.query(ReconciliationRun)
        .filter(
            ReconciliationRun.supplier_id == supplier_id,
            ReconciliationRun.period == period,
            ReconciliationRun.status == "completed",
            ReconciliationRun.id != run.id,
        )
        .order_by(desc(ReconciliationRun.started_at))
        .first()
    )
    if prev_run is None:
        return

    prior = (
        db.query(ReconciliationResult)
        .filter(
            ReconciliationResult.run_id == prev_run.id,
            or_(
                ReconciliationResult.marked_discrepancy_reason.isnot(None),
                ReconciliationResult.status == "resolved",
            ),
        )
        .all()
    )
    if not prior:
        return

    def _key(r: ReconciliationResult) -> tuple:
        return (
            r.erp_record_id,
            r.statement_line_id,
            r.discrepancy_type,
            r.quantity_delta,
            r.price_delta,
        )

    prior_by_key = {_key(r): r for r in prior}
    carried_marks = carried_resolves = 0
    for r in all_results:
        p = prior_by_key.get(_key(r))
        if p is None:
            continue
        if p.marked_discrepancy_reason is not None and r.marked_discrepancy_reason is None:
            r.marked_discrepancy_reason = p.marked_discrepancy_reason
            r.marked_discrepancy_by = p.marked_discrepancy_by
            r.marked_discrepancy_at = p.marked_discrepancy_at
            carried_marks += 1
        if p.status == "resolved" and r.status != "resolved":
            r.status = "resolved"
            r.resolution_note = p.resolution_note
            r.resolved_by = p.resolved_by
            r.resolved_at = p.resolved_at
            carried_resolves += 1
    if carried_marks or carried_resolves:
        logger.info(
            "[RECON DEBUG] Carried forward review state from run %s: "
            "%d marks, %d resolutions",
            prev_run.id, carried_marks, carried_resolves,
        )


async def run_reconciliation(
    supplier_id: Any,
    period: str,
    db: Session,
) -> ReconciliationRun:
    """Execute reconciliation for a supplier+period.

    Waterfall: combine identical rows (both sides) → Layer 1 (exact) →
    Layer 2 (fuzzy) → unmatched tail with suggest-only AI hints.
    """
    # Verify supplier exists
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise ValueError(f"Supplier {supplier_id} not found")

    # Load config
    config = _load_config(db, supplier.org_id)
    qty_tol = Decimal(str(config["qty_tolerance_pct"]))
    price_tol = Decimal(str(config["price_tolerance_pct"]))
    date_tol_days = int(config["date_tolerance_days"])

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
        # Load ERP records for supplier+period. Scope is the upload's PERIOD
        # TAG, never grn_date: monthly exports contain overflowed dates (a
        # "March" export carries late-February receipts) and ERP bookings can
        # trail supplier records by weeks. Dates only combine rows and break
        # ties. Legacy untagged rows fall back to their grn_date month.
        period_start, period_end = _period_date_range(period)
        logger.info(
            "[RECON DEBUG] Starting reconciliation: supplier_id=%s, period=%s",
            supplier_id, period,
        )

        erp_records = (
            db.query(ERPRecord)
            .filter(
                ERPRecord.supplier_id == supplier_id,
                or_(
                    ERPRecord.period == period,
                    and_(
                        ERPRecord.period.is_(None),
                        ERPRecord.grn_date >= period_start,
                        ERPRecord.grn_date <= period_end,
                    ),
                ),
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

        # Carryover: unresolved missing-from-statement receipts from prior
        # periods become candidates — the supplier may finally have included
        # them in this month's statement.
        carryover_records, carryover_origin, carryover_prior = _load_carryover(
            db, supplier_id, period
        )
        period_erp_ids = {r.id for r in erp_records}
        carryover_records = [r for r in carryover_records if r.id not in period_erp_ids]
        carryover_origin = {
            k: v for k, v in carryover_origin.items() if k not in period_erp_ids
        }
        if carryover_records:
            logger.info(
                "[RECON DEBUG] Carryover: %d unresolved missing-from-statement "
                "receipts from prior periods join as candidates",
                len(carryover_records),
            )

        erp_candidates = [_erp_to_candidate(r) for r in erp_records] + [
            _erp_to_candidate(r) for r in carryover_records
        ]
        stmt_items = [_stmt_to_item(l) for l in stmt_lines]

        # Identical-row combining on BOTH sides: rows sharing PO, material,
        # date, and per-unit price collapse into one (quantity/amount summed).
        # Statement side mirrors the factory's practice of keying several
        # supplier lines as one receipt; ERP side handles the clerk forgetting
        # to combine same-day receipts. After this, each side holds at most
        # one row per (PO, material, price, date) and matching is a key join.
        raw_stmt_count = len(stmt_items)
        stmt_items, combined_groups = combine_statement_lines(stmt_items)
        if combined_groups:
            logger.info(
                "[RECON DEBUG] Pre-aggregation: %d raw statement lines combined "
                "into %d (%d groups)",
                raw_stmt_count, len(stmt_items), len(combined_groups),
            )
        raw_erp_count = len(erp_candidates)
        erp_candidates, erp_combined_groups = combine_erp_records(erp_candidates)
        if erp_combined_groups:
            logger.info(
                "[RECON DEBUG] Pre-aggregation: %d raw ERP receipts combined "
                "into %d (%d groups)",
                raw_erp_count, len(erp_candidates), len(erp_combined_groups),
            )

        # total_erp counts THIS period's receipts only — carryover candidates
        # belong to their origin period and would distort the period totals.
        # Counted after combining (like total_statement) so both totals mean
        # "logical receipts"; carryover rows can never merge with this
        # period's rows because their GRN dates lie in earlier periods.
        run.total_erp = sum(1 for e in erp_candidates if e.erp_id in period_erp_ids)
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

        # Layer 1: Strict exact match — identical PO + material + unit price,
        # dates within ±date_tol_days. Quantity is the only field allowed to
        # deviate (it becomes a quantity discrepancy on the pair).
        l1_matches, unmatched_erp, unmatched_stmt = run_exact_match(
            erp_candidates, stmt_items, qty_tol, price_tol, date_tol_days
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

        # Layer 2: Fuzzy match — same strict semantics, looser key normalization
        l2_matches, unmatched_erp, unmatched_stmt = run_fuzzy_match(
            unmatched_erp, unmatched_stmt, qty_tol, price_tol, date_tol_days
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

        # AI layer (suggest-only): every leftover stays unmatched; Claude's
        # pairing hints are attached to the unmatched rows below so the
        # accountant can confirm or reject them. Never counts as matched.
        ai_suggestions: list[dict[str, Any]] = []
        if config["ai_layer_enabled"] and unmatched_erp and unmatched_stmt:
            logger.info(
                "[RECON DEBUG] AI suggestions: sending %d ERP + %d stmt to Claude",
                len(unmatched_erp), len(unmatched_stmt),
            )
            ai_suggestions = await run_ai_suggestions(
                unmatched_erp,
                unmatched_stmt,
                anthropic_api_key=settings.anthropic_api_key,
                max_tokens=config["ai_max_tokens_per_run"],
            )
            logger.info(
                "[RECON DEBUG] AI suggestions: %d possible pairings surfaced",
                len(ai_suggestions),
            )
        else:
            logger.info("[RECON DEBUG] AI suggestions skipped (disabled or nothing unmatched)")

        # Create unmatched results for remaining ERP records
        unmatched_result_by_erp: dict[Any, ReconciliationResult] = {}
        for erp in unmatched_erp:
            result = ReconciliationResult(
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
            )
            unmatched_result_by_erp[erp.erp_id] = result
            all_results.append(result)

        # Create unmatched results for remaining statement items
        unmatched_result_by_stmt: dict[Any, ReconciliationResult] = {}
        for stmt in unmatched_stmt:
            result = ReconciliationResult(
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
            )
            unmatched_result_by_stmt[stmt.line_id] = result
            all_results.append(result)

        # Attach AI pairing hints to both sides of each suggestion. The rows
        # remain unmatched (and keep counting as missing) — the hint is
        # informational until a human confirms it.
        for sug in ai_suggestions:
            pct = round(sug["confidence"] * 100)
            erp_result = unmatched_result_by_erp.get(sug["erp_id"])
            if erp_result is not None:
                erp_result.match_details = {
                    **(erp_result.match_details or {}),
                    "ai_suggestion": {
                        "statement_line_id": str(sug["stmt_line_id"]),
                        "confidence": sug["confidence"],
                        "reason": sug["reason"],
                    },
                }
                erp_result.discrepancy_note = (
                    f"AI suggests a possible statement counterpart "
                    f"({pct}% confidence): {sug['reason']}"
                )
            stmt_result = unmatched_result_by_stmt.get(sug["stmt_line_id"])
            if stmt_result is not None:
                stmt_result.match_details = {
                    **(stmt_result.match_details or {}),
                    "ai_suggestion": {
                        "erp_record_id": str(sug["erp_id"]),
                        "confidence": sug["confidence"],
                        "reason": sug["reason"],
                    },
                }
                stmt_result.discrepancy_note = (
                    f"AI suggests a possible ERP counterpart "
                    f"({pct}% confidence): {sug['reason']}"
                )

        # Final summary
        logger.info(
            "[RECON DEBUG] === FINAL SUMMARY ===\n"
            "  Total results: %d\n"
            "  Unmatched ERP (missing from statement): %d\n"
            "  Unmatched stmt (missing from ERP): %d\n"
            "  Layer breakdown: L1=%d, L2=%d, AI suggestions=%d",
            len(all_results),
            len(unmatched_erp), len(unmatched_stmt),
            len(l1_matches), len(l2_matches), len(ai_suggestions),
        )
        if unmatched_erp:
            sample_erp = [(e.po_number, e.material_number, str(e.quantity)) for e in unmatched_erp[:5]]
            logger.info("[RECON DEBUG] Sample unmatched ERP: %s", sample_erp)
        if unmatched_stmt:
            sample_stmt = [(s.po_number, s.material_number, str(s.quantity)) for s in unmatched_stmt[:5]]
            logger.info("[RECON DEBUG] Sample unmatched stmt: %s", sample_stmt)

        # Carryover bookkeeping: stamp each result touching a carried-over
        # receipt with its origin period, and close the loop — a prior-period
        # missing_from_statement result whose item finally matched resolves
        # automatically (unless that period is signed off / locked).
        if carryover_origin:
            matched_carryover: set[Any] = set()
            for r in all_results:
                origin_period = carryover_origin.get(r.erp_record_id)
                if origin_period is None:
                    continue
                r.match_details = {
                    **(r.match_details or {}),
                    "carryover_from": origin_period,
                }
                if r.match_type != "unmatched":
                    matched_carryover.add(r.erp_record_id)

            if matched_carryover:
                locked_periods = {
                    p
                    for (p,) in db.query(PeriodSignoff.period).filter(
                        PeriodSignoff.org_id == supplier.org_id,
                        PeriodSignoff.status == "signed_off",
                    )
                }
                resolved_n = 0
                for erp_id in matched_carryover:
                    for prior in carryover_prior.get(erp_id, []):
                        if prior.period in locked_periods:
                            continue
                        prior.status = "resolved"
                        prior.resolution_note = (
                            f"Carried forward: matched in {period} statement"
                        )
                        prior.resolved_by = "system"
                        prior.resolved_at = datetime.utcnow()
                        resolved_n += 1
                logger.info(
                    "[RECON DEBUG] Carryover: %d receipts matched this period; "
                    "%d prior-period discrepancies auto-resolved",
                    len(matched_carryover), resolved_n,
                )

        # Stamp results that reference a pre-aggregated statement line with the
        # group's raw-line ids and totals, so the mismatch API can show the
        # combined qty/amount and the annotated export can write the group
        # verdict onto every raw supplier row.
        if combined_groups:
            for r in all_results:
                grp = combined_groups.get(r.statement_line_id)
                if grp is not None:
                    r.match_details = {
                        **(r.match_details or {}),
                        "stmt_combined_lines": len(grp.line_ids),
                        "stmt_combined_line_ids": [str(i) for i in grp.line_ids],
                        "stmt_combined_qty": float(grp.quantity),
                        "stmt_combined_amount": float(grp.amount),
                    }

        # Same for combined ERP receipts: results reference the group's
        # primary erp_record_id, so stamp the raw receipt ids and totals.
        if erp_combined_groups:
            for r in all_results:
                grp = erp_combined_groups.get(r.erp_record_id)
                if grp is not None:
                    r.match_details = {
                        **(r.match_details or {}),
                        "erp_combined_lines": len(grp.line_ids),
                        "erp_combined_line_ids": [str(i) for i in grp.line_ids],
                        "erp_combined_qty": float(grp.quantity),
                        "erp_combined_amount": float(grp.amount),
                    }

        # Bulk insert results
        db.add_all(all_results)

        # Preserve human review state (marks/resolves) across re-runs.
        _carry_forward_review_state(db, supplier_id, period, run, all_results)

        # Update run stats (see _compute_run_stats for the counting rules).
        stats = _compute_run_stats(all_results, run.total_statement)
        run.matched_count = stats["matched_count"]
        run.discrepancy_count = stats["discrepancy_count"]
        run.unmatched_count = stats["unmatched_count"]
        run.auto_match_rate = stats["auto_match_rate"]

        logger.info(
            "[RECON DEBUG] Match rate: %d matched / (%d statement items + %d "
            "missing from statement) = %.1f%%.",
            stats["matched_count"], run.total_statement or 0,
            stats["unmatched_erp_count"],
            float(run.auto_match_rate),
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
