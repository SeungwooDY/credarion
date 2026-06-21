"""
Context-aware AI chat endpoint.

Loads live data from the database so the assistant always has context,
regardless of which page the user is on.
"""

import json
import logging
import uuid
from collections import defaultdict
from decimal import Decimal

import anthropic
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func

from app.config import settings
from app.db import SessionLocal
from app.models import (
    ERPRecord,
    Invoice,
    Organization,
    ReconciliationResult,
    ReconciliationRun,
    StatementLineItem,
    Supplier,
    SupplierStatement,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

SYSTEM_PROMPT = """\
You are Credarion Assistant, an AI accounting co-pilot embedded inside Credarion — \
a reconciliation and invoice processing platform for Asia-Pacific mid-market companies.

IMPORTANT RULES:
1. You have access to the user's live database via the <context> block in each message. \
This is real data queried from their Credarion instance — reference it directly.
2. ONLY reference data that is actually present in the context. Do NOT assume, \
fabricate, or guess specific PO numbers, amounts, suppliers, or counts that are \
not explicitly listed in the context block.
3. When the context includes mismatch details for a supplier, analyze those specific items: \
cite PO numbers, quantities, prices, and amounts.
4. When the context includes only summary-level data (supplier list, counts), work with that. \
Do not invent line-item details.
5. Keep responses concise and actionable. Use bullet points for lists.
6. Do NOT use heading levels (# ## ###) — the chat panel is small. Use **bold** for emphasis.
7. Use accounting terminology appropriate for APAC mid-market companies.\

Your capabilities:
- Analyze mismatches: explain why items failed to match, identify patterns, \
  quantify impact (total amount at risk)
- Suggest actions: contact supplier, correct ERP entry, approve variance, flag for review
- Summarize: group issues by type, rank by severity/amount, highlight priorities
- Explain: reconciliation concepts, match layers, discrepancy types
- Answer questions about invoices, suppliers, and ERP data\
"""


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []
    org_id: str | None = None


def _decimal(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _load_db_context(org_id: str | None) -> str:
    """Query the database and build a context string for the LLM."""
    parts: list[str] = []

    db = SessionLocal()
    try:
        # ── Organizations ──
        orgs = db.query(Organization).all()
        if not orgs:
            parts.append("No organizations in the system yet. The user needs to create one first.")
            return "\n".join(parts)

        parts.append(f"Organizations ({len(orgs)}):")
        for o in orgs:
            parts.append(f"  - {o.name} (currency: {o.reporting_currency}, id: {o.id})")

        # Pick the active org
        active_org = None
        if org_id:
            try:
                uid = uuid.UUID(org_id)
                active_org = db.query(Organization).filter(Organization.id == uid).first()
            except ValueError:
                pass
        if not active_org:
            active_org = orgs[0]

        parts.append(f"\nActive organization: {active_org.name}")

        # ── Suppliers ──
        suppliers = (
            db.query(Supplier)
            .filter(Supplier.org_id == active_org.id)
            .order_by(Supplier.name)
            .all()
        )
        parts.append(f"\nSuppliers ({len(suppliers)}):")
        for s in suppliers:
            parts.append(f"  - {s.name} (code: {s.vendor_code})")

        # ── ERP record counts ──
        erp_count = (
            db.query(func.count(ERPRecord.id))
            .filter(ERPRecord.org_id == active_org.id)
            .scalar()
        )
        parts.append(f"\nERP records: {erp_count}")

        # ── Statement counts ──
        stmt_count = (
            db.query(func.count(SupplierStatement.id))
            .join(Supplier, SupplierStatement.supplier_id == Supplier.id)
            .filter(Supplier.org_id == active_org.id)
            .scalar()
        )
        parts.append(f"Supplier statements uploaded: {stmt_count}")

        # ── Latest reconciliation runs ──
        latest_runs = (
            db.query(ReconciliationRun)
            .join(Supplier, ReconciliationRun.supplier_id == Supplier.id)
            .filter(
                Supplier.org_id == active_org.id,
                ReconciliationRun.status == "completed",
            )
            .order_by(desc(ReconciliationRun.started_at))
            .limit(20)
            .all()
        )

        # Deduplicate to latest per supplier
        seen_suppliers: set[uuid.UUID] = set()
        unique_runs: list[ReconciliationRun] = []
        for run in latest_runs:
            if run.supplier_id not in seen_suppliers:
                seen_suppliers.add(run.supplier_id)
                unique_runs.append(run)

        if unique_runs:
            supplier_map = {s.id: s for s in suppliers}
            parts.append(f"\n--- RECONCILIATION SUMMARY ({len(unique_runs)} suppliers with completed runs) ---")
            for run in unique_runs:
                s = supplier_map.get(run.supplier_id)
                sname = s.name if s else "Unknown"
                rate = f"{_decimal(run.auto_match_rate)}%" if run.auto_match_rate is not None else "N/A"
                parts.append(
                    f"  {sname} (period: {run.period}): "
                    f"match rate {rate}, "
                    f"{run.matched_count} matched, "
                    f"{run.discrepancy_count} discrepancies, "
                    f"{run.unmatched_count} unmatched"
                )

            # ── Top mismatches (discrepancies from latest runs) ──
            # Nothing auto-matches now; a "discrepancy" is any result carrying a
            # discrepancy_type (near_exact deltas, unmatched, or layer deltas),
            # regardless of its pending/confirmed/rejected review status.
            run_ids = [r.id for r in unique_runs]
            mismatches = (
                db.query(ReconciliationResult)
                .filter(
                    ReconciliationResult.run_id.in_(run_ids),
                    ReconciliationResult.discrepancy_type.isnot(None),
                )
                .limit(60)
                .all()
            )

            if mismatches:
                # Load related ERP + statement records
                erp_ids = [m.erp_record_id for m in mismatches if m.erp_record_id]
                stmt_ids = [m.statement_line_id for m in mismatches if m.statement_line_id]

                erp_map: dict[uuid.UUID, ERPRecord] = {}
                if erp_ids:
                    for e in db.query(ERPRecord).filter(ERPRecord.id.in_(erp_ids)).all():
                        erp_map[e.id] = e

                stmt_map: dict[uuid.UUID, StatementLineItem] = {}
                if stmt_ids:
                    for sl in db.query(StatementLineItem).filter(StatementLineItem.id.in_(stmt_ids)).all():
                        stmt_map[sl.id] = sl

                # Group by supplier
                by_supplier: dict[uuid.UUID, list] = defaultdict(list)
                for m in mismatches:
                    by_supplier[m.supplier_id].append(m)

                parts.append(f"\n--- MISMATCH DETAILS ({len(mismatches)} items) ---")
                for sid, items in by_supplier.items():
                    s = supplier_map.get(sid)
                    sname = s.name if s else "Unknown"
                    parts.append(f"\n  Supplier: {sname} ({len(items)} discrepancies)")
                    for i, m in enumerate(items[:25]):
                        line_parts = []
                        erp = erp_map.get(m.erp_record_id) if m.erp_record_id else None
                        stmt = stmt_map.get(m.statement_line_id) if m.statement_line_id else None

                        po = (erp.po_number if erp else None) or (stmt.po_number if stmt else None)
                        part = (erp.material_number if erp else None) or (stmt.material_number if stmt else None)

                        if po:
                            line_parts.append(f"PO={po}")
                        if part:
                            line_parts.append(f"Part={part}")
                        if m.discrepancy_type:
                            line_parts.append(f"Issue={m.discrepancy_type}")
                        if m.quantity_delta is not None:
                            line_parts.append(f"QtyDelta={_decimal(m.quantity_delta)}")
                        if m.price_delta is not None:
                            line_parts.append(f"PriceDelta={_decimal(m.price_delta)}")
                        if m.amount_delta is not None:
                            line_parts.append(f"AmtDelta={_decimal(m.amount_delta)}")

                        # Include actual values for context
                        if erp:
                            line_parts.append(f"ERP_Qty={_decimal(erp.quantity)}")
                            line_parts.append(f"ERP_Price={_decimal(erp.po_price)}")
                        if stmt:
                            line_parts.append(f"Stmt_Qty={_decimal(stmt.quantity)}")
                            line_parts.append(f"Stmt_Price={_decimal(stmt.unit_price)}")

                        parts.append(f"    [{i+1}] " + ", ".join(line_parts))
                    if len(items) > 25:
                        parts.append(f"    ... and {len(items) - 25} more for this supplier")
        else:
            parts.append("\nNo reconciliation runs completed yet.")

        # ── Invoice summary ──
        try:
            invoice_stats = (
                db.query(Invoice.status, func.count(Invoice.id))
                .filter(Invoice.org_id == active_org.id)
                .group_by(Invoice.status)
                .all()
            )
            if invoice_stats:
                total_inv = sum(c for _, c in invoice_stats)
                parts.append(f"\n--- INVOICES ({total_inv} total) ---")
                for status, count in invoice_stats:
                    parts.append(f"  {status}: {count}")

                review_count = (
                    db.query(func.count(Invoice.id))
                    .filter(Invoice.org_id == active_org.id, Invoice.needs_review.is_(True))
                    .scalar()
                )
                if review_count:
                    parts.append(f"  Needs review: {review_count}")
            else:
                parts.append("\nNo invoices uploaded yet.")
        except Exception:
            db.rollback()
            parts.append("\nInvoice data not available (table not yet created).")

    finally:
        db.close()

    return "\n".join(parts)


@router.post("/ask")
async def chat_ask(req: ChatRequest):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    context_block = _load_db_context(req.org_id)

    messages: list[dict] = []
    for msg in req.history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    user_content = f"<context>\n{context_block}\n</context>\n\n{req.message}"
    messages.append({"role": "user", "content": user_content})

    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=httpx.Timeout(30.0, connect=5.0),
    )

    async def generate():
        try:
            async with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except anthropic.APIError as e:
            logger.error("Chat API error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
