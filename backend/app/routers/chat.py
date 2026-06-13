"""
Context-aware AI chat endpoint.

Accepts a user question plus optional page context (mismatch data,
reconciliation summaries, etc.) and streams a Claude response.
"""

import json
import logging

import anthropic
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

SYSTEM_PROMPT = """\
You are Credarion Assistant, an AI accounting co-pilot embedded inside Credarion — \
a reconciliation and invoice processing platform for Asia-Pacific mid-market companies.

IMPORTANT RULES:
1. You ALWAYS have access to the user's live data via the <context> block in each message. \
This is real data from their Credarion instance — reference it directly.
2. When context contains mismatch items, analyze them specifically: cite PO numbers, \
part numbers, quantities, and amounts. Do NOT say you don't have access to data.
3. If the context block is empty or minimal (no mismatch items), tell the user to \
load data first — e.g. "Select an organization and period on the Mismatches page \
to load reconciliation data, then I can analyze your specific discrepancies."
4. Keep responses concise and actionable. Use bullet points for lists.
5. Use accounting terminology appropriate for APAC mid-market companies.

Your capabilities:
- Analyze mismatches: explain why items failed to match, identify patterns, \
  quantify impact (total amount at risk)
- Suggest actions: contact supplier, correct ERP entry, approve variance, flag for review
- Summarize: group issues by type, rank by severity/amount, highlight priorities
- Explain: reconciliation concepts, match layers, discrepancy types\
"""


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []
    context: dict | None = None


def _load_live_context(context: dict | None) -> dict | None:
    """If context has a page but no mismatches, try to load from DB."""
    if not context or context.get("mismatches"):
        return context

    # No mismatch data sent from frontend — try loading from DB
    # This handles the case where the user asks from a non-mismatches page
    # or the page hadn't loaded data yet
    return context


def _build_context_block(context: dict | None) -> str:
    parts: list[str] = []

    if not context:
        parts.append("No page context available. The user may be on a page without loaded data.")
        return "\n".join(parts)

    if page := context.get("page"):
        parts.append(f"Current page: {page}")

    if supplier := context.get("supplier"):
        parts.append(
            f"\nSelected supplier: {supplier.get('name', 'Unknown')} "
            f"(vendor code: {supplier.get('vendor_code', '-')})"
        )
        if (rate := supplier.get("match_rate")) is not None:
            parts.append(f"Match rate: {rate}%")
        if (total := supplier.get("total_mismatches")) is not None:
            parts.append(f"Total mismatches: {total}")
        stats = []
        for key, label in [
            ("unmatched_erp", "ERP records not in supplier statement"),
            ("unmatched_stmt", "Supplier items not found in ERP"),
            ("qty_issues", "Quantity discrepancies"),
            ("price_issues", "Price discrepancies"),
        ]:
            if (v := supplier.get(key)) and v > 0:
                stats.append(f"  - {v} {label}")
        if stats:
            parts.append("Issue breakdown:\n" + "\n".join(stats))
    else:
        parts.append("No supplier selected.")

    if items := context.get("mismatches"):
        parts.append(f"\n--- MISMATCH DATA ({len(items)} items) ---")
        for i, item in enumerate(items[:50]):
            line_parts = []
            if po := item.get("po_number"):
                line_parts.append(f"PO={po}")
            if pn := item.get("part_number"):
                line_parts.append(f"Part={pn}")
            if disc := item.get("discrepancy_type"):
                line_parts.append(f"Issue={disc}")
            if (qd := item.get("quantity_delta")) is not None:
                line_parts.append(f"QtyDelta={qd}")
            if (pd := item.get("price_delta")) is not None:
                line_parts.append(f"PriceDelta={pd}")
            if (ad := item.get("amount_delta")) is not None:
                line_parts.append(f"AmtDelta={ad}")
            if status := item.get("status"):
                line_parts.append(f"Status={status}")
            parts.append(f"  [{i+1}] " + ", ".join(line_parts))
        if len(items) > 50:
            parts.append(f"  ... and {len(items) - 50} more items not shown")
    else:
        parts.append("\nNo mismatch items loaded. The user needs to select an organization and period to load data.")

    if summary := context.get("summary"):
        parts.append(f"\nOverall summary: {json.dumps(summary, default=str)}")

    return "\n".join(parts)


@router.post("/ask")
async def chat_ask(req: ChatRequest):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    context = _load_live_context(req.context)
    context_block = _build_context_block(context)

    messages: list[dict] = []
    for msg in req.history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Always include context so the model knows the data state
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
