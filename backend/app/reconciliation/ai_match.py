"""Layer 4: AI-powered matching using Claude Haiku as fallback.

Batches unmatched items and asks Claude to find potential matches
based on contextual similarity. Only accepts matches with confidence >= 0.7.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import anthropic

from app.reconciliation.exact_match import (
    MatchCandidate,
    MatchResult,
    StatementItem,
    _classify_discrepancy,
    _within_tolerance,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 15
CONFIDENCE_THRESHOLD = Decimal("0.70")

_SYSTEM_PROMPT = """You are a supplier reconciliation assistant for a Chinese manufacturing company.
You are given unmatched ERP goods receipt records and supplier statement line items.
Your job is to identify potential matches between them based on contextual clues:
- Similar PO numbers (with typos, different formatting)
- Similar material/part numbers
- Matching quantities or amounts
- Date proximity

Return a JSON array of match objects. Each match object must have:
{
  "erp_index": <int>,       // 0-based index into the ERP list
  "stmt_index": <int>,      // 0-based index into the statement list
  "confidence": <float>,    // 0.0 to 1.0
  "reason": <string>        // brief explanation
}

Only include matches where you are reasonably confident (>= 0.7).
If no matches are found, return an empty array: []
Return ONLY the JSON array, no other text."""


def _format_erp_for_prompt(items: list[MatchCandidate]) -> str:
    lines = []
    for i, e in enumerate(items):
        lines.append(
            f"[{i}] PO={e.po_number} Material={e.material_number} "
            f"Qty={e.quantity} Price={e.po_price} Amount={e.amount} "
            f"GRN_Date={e.grn_date.strftime('%Y-%m-%d') if e.grn_date else 'N/A'} "
            f"DN={e.delivery_note or 'N/A'}"
        )
    return "\n".join(lines)


def _format_stmt_for_prompt(items: list[StatementItem]) -> str:
    lines = []
    for i, s in enumerate(items):
        lines.append(
            f"[{i}] PO={s.po_number or 'N/A'} Material={s.material_number or 'N/A'} "
            f"Qty={s.quantity} Price={s.unit_price} Amount={s.amount} "
            f"Date={s.delivery_date or 'N/A'} DN_Ref={s.delivery_note_ref or 'N/A'}"
        )
    return "\n".join(lines)


async def run_ai_match(
    erp_records: list[MatchCandidate],
    statement_items: list[StatementItem],
    qty_tolerance_pct: Decimal = Decimal("0.50"),
    price_tolerance_pct: Decimal = Decimal("0.50"),
    anthropic_api_key: str | None = None,
    max_tokens: int = 10000,
) -> tuple[list[MatchResult], list[MatchCandidate], list[StatementItem]]:
    """Run Layer 4 AI matching on remaining unmatched items.

    Returns:
        (matches, unmatched_erp, unmatched_statement)
    """
    if not anthropic_api_key:
        logger.info("AI layer skipped: no API key configured")
        return [], erp_records, statement_items

    if not erp_records or not statement_items:
        return [], erp_records, statement_items

    try:
        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    except Exception as e:
        logger.warning("AI layer unavailable: %s", e)
        return [], erp_records, statement_items

    all_matches: list[MatchResult] = []
    matched_erp_ids: set = set()
    matched_stmt_ids: set = set()
    tokens_used = 0

    # Process in batches
    erp_batches = [
        erp_records[i : i + BATCH_SIZE]
        for i in range(0, len(erp_records), BATCH_SIZE)
    ]
    stmt_batches = [
        statement_items[i : i + BATCH_SIZE]
        for i in range(0, len(statement_items), BATCH_SIZE)
    ]

    for erp_batch in erp_batches:
        for stmt_batch in stmt_batches:
            if tokens_used >= max_tokens:
                break

            # Filter already matched
            erp_avail = [e for e in erp_batch if e.erp_id not in matched_erp_ids]
            stmt_avail = [s for s in stmt_batch if s.line_id not in matched_stmt_ids]
            if not erp_avail or not stmt_avail:
                continue

            prompt = (
                f"ERP Records:\n{_format_erp_for_prompt(erp_avail)}\n\n"
                f"Statement Items:\n{_format_stmt_for_prompt(stmt_avail)}"
            )

            try:
                response = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                tokens_used += response.usage.input_tokens + response.usage.output_tokens

                text = response.content[0].text.strip()
                # Extract JSON from potential markdown code blocks
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()

                ai_matches = json.loads(text)
            except Exception as e:
                logger.warning("AI batch failed: %s", e)
                continue

            for m in ai_matches:
                erp_idx = m.get("erp_index")
                stmt_idx = m.get("stmt_index")
                conf = Decimal(str(m.get("confidence", 0)))

                if conf < CONFIDENCE_THRESHOLD:
                    continue
                if erp_idx is None or stmt_idx is None:
                    continue
                if erp_idx >= len(erp_avail) or stmt_idx >= len(stmt_avail):
                    continue

                erp = erp_avail[erp_idx]
                stmt = stmt_avail[stmt_idx]

                if erp.erp_id in matched_erp_ids or stmt.line_id in matched_stmt_ids:
                    continue

                matched_erp_ids.add(erp.erp_id)
                matched_stmt_ids.add(stmt.line_id)

                qty_delta = stmt.quantity - erp.quantity
                price_delta = stmt.unit_price - erp.po_price
                amount_delta = stmt.amount - erp.amount

                qty_ok = _within_tolerance(erp.quantity, stmt.quantity, qty_tolerance_pct)
                price_ok = _within_tolerance(erp.po_price, stmt.unit_price, price_tolerance_pct)

                if qty_ok and price_ok:
                    status = "matched"
                    disc_type = None
                else:
                    status = "discrepancy"
                    disc_type = _classify_discrepancy(qty_delta, price_delta)

                all_matches.append(MatchResult(
                    erp=erp,
                    statement=stmt,
                    match_type="ai",
                    quantity_delta=qty_delta,
                    price_delta=price_delta,
                    amount_delta=amount_delta,
                    status=status,
                    discrepancy_type=disc_type,
                    confidence=conf,
                    match_details={
                        "layer": 4,
                        "ai_reason": m.get("reason", ""),
                        "ai_confidence": float(conf),
                    },
                ))

        if tokens_used >= max_tokens:
            break

    unmatched_erp = [e for e in erp_records if e.erp_id not in matched_erp_ids]
    unmatched_stmt = [s for s in statement_items if s.line_id not in matched_stmt_ids]

    return all_matches, unmatched_erp, unmatched_stmt
