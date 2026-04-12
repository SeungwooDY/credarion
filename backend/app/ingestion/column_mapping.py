"""Three-tier column mapping: alias dict → LLM → human review.

Maps Chinese column headers from supplier statements to canonical field names
used by StatementLineItem.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import SupplierColumnMapping

logger = logging.getLogger(__name__)

# Canonical fields we need to extract
CANONICAL_FIELDS = [
    "po_number",
    "material_number",
    "quantity",
    "unit_price",
    "amount",
    "delivery_date",
    "delivery_note_ref",
]

# Minimum required fields for a successful mapping
REQUIRED_FIELDS = {"po_number", "quantity", "amount"}

# Tier 1 — Alias map covering all 5 known suppliers
# Keys are canonical field names, values are lists of known Chinese aliases
ALIAS_MAP: dict[str, list[str]] = {
    "po_number": [
        "订单单号",
        "订单号",
    ],
    "material_number": [
        "规格型号1",
        "规格型号",
        "对应代码",
        "物料编码",
        "产品型号",
        "客户料号",
    ],
    "quantity": [
        "实发数量",
        "数量",
        "数量(PCS)",
        "数量(P)",
        "数量（P)",
        "数量(P",
    ],
    "unit_price": [
        "销售单价",
        "单价",
        "单价(RMB)",
        "单价(R)",
        "单价（R)",
        "单价（RMB）",
        "采购单单价",
    ],
    "amount": [
        "销售金额",
        "金额",
        "含税金额",
        "金额合计",
        "金额(R)",
        "金额（R)",
        "金额（RMB）",
    ],
    "delivery_date": [
        "日期",
        "送货日期",
        "交货日期",
    ],
    "delivery_note_ref": [
        "单据编号",
        "送货单号",
    ],
}

# Build reverse lookup: Chinese header → canonical field
_REVERSE_ALIAS: dict[str, str] = {}
for field, aliases in ALIAS_MAP.items():
    for alias in aliases:
        _REVERSE_ALIAS[alias] = field


def _normalize_header(h: str) -> str:
    """Normalize a header string for alias lookup."""
    s = h.strip()
    # Full-width parens → half-width
    s = s.replace("（", "(").replace("）", ")")
    return s


def try_alias_mapping(headers: list[str]) -> dict[str, str] | None:
    """Tier 1: Try to map headers using the alias dictionary.

    Returns:
        Dict mapping canonical field name → original column header,
        or None if required fields can't be mapped.
    """
    mapping: dict[str, str] = {}
    for header in headers:
        if not header:
            continue
        normalized = _normalize_header(header)
        if normalized in _REVERSE_ALIAS:
            canonical = _REVERSE_ALIAS[normalized]
            if canonical not in mapping:  # first match wins
                mapping[canonical] = header

    if REQUIRED_FIELDS.issubset(mapping.keys()):
        return mapping
    return None


async def try_llm_mapping(
    headers: list[str], sample_rows: list[list[str]]
) -> dict[str, str] | None:
    """Tier 2: Use Claude API to map unfamiliar headers.

    Returns:
        Dict mapping canonical field name → original column header,
        or None if LLM fails or required fields can't be mapped.
    """
    if not settings.anthropic_api_key:
        logger.warning("No ANTHROPIC_API_KEY configured, skipping LLM mapping")
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception:
        logger.exception("Failed to initialize Anthropic client")
        return None

    prompt = f"""You are mapping Chinese column headers from a supplier reconciliation statement
to canonical field names.

The column headers are: {json.dumps(headers, ensure_ascii=False)}

Here are 2-3 sample data rows:
{json.dumps(sample_rows, ensure_ascii=False)}

Map each header to one of these canonical fields (if applicable):
- po_number: Purchase order number (订单号)
- material_number: Part/material code (物料编码/型号)
- quantity: Quantity delivered
- unit_price: Price per unit
- amount: Total amount (price × quantity)
- delivery_date: Date of delivery
- delivery_note_ref: Delivery note reference number

Return ONLY a JSON object mapping canonical field names to the original column header strings.
Example: {{"po_number": "订单号", "quantity": "数量", "amount": "金额"}}

Only include fields you are confident about. Do not include fields that don't have a match."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Extract JSON from response (may be wrapped in markdown code block)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        mapping = json.loads(text)

        # Validate that returned column names actually exist in headers
        validated: dict[str, str] = {}
        for field, col_name in mapping.items():
            if field in CANONICAL_FIELDS and col_name in headers:
                validated[field] = col_name

        if REQUIRED_FIELDS.issubset(validated.keys()):
            return validated

        logger.warning("LLM mapping missing required fields: %s", validated)
        return None

    except Exception:
        logger.exception("LLM column mapping failed")
        return None


def get_cached_mapping(supplier_id: uuid.UUID, db: Session) -> SupplierColumnMapping | None:
    """Check if we have a cached (non-review) mapping for this supplier."""
    return (
        db.query(SupplierColumnMapping)
        .filter(
            SupplierColumnMapping.supplier_id == supplier_id,
            SupplierColumnMapping.needs_review.is_(False),
        )
        .first()
    )


def upsert_mapping(
    supplier_id: uuid.UUID,
    column_map: dict[str, str],
    source: str,
    header_row: int,
    db: Session,
    confidence: float | None = None,
    needs_review: bool = False,
) -> SupplierColumnMapping:
    """Insert or update a supplier column mapping."""
    existing = (
        db.query(SupplierColumnMapping)
        .filter(SupplierColumnMapping.supplier_id == supplier_id)
        .first()
    )

    if existing:
        existing.column_map = column_map
        existing.source = source
        existing.header_row = header_row
        existing.confidence = confidence
        existing.needs_review = needs_review
        db.flush()
        return existing

    mapping = SupplierColumnMapping(
        supplier_id=supplier_id,
        column_map=column_map,
        source=source,
        header_row=header_row,
        confidence=confidence,
        needs_review=needs_review,
    )
    db.add(mapping)
    db.flush()
    return mapping


async def resolve_column_mapping(
    headers: list[str],
    sample_rows: list[list[str]],
    supplier_id: uuid.UUID,
    header_row: int,
    db: Session,
) -> tuple[dict[str, str], str, bool]:
    """Run the three-tier mapping pipeline.

    Returns:
        (column_map, source, needs_review)
    """
    # Tier 1 — alias dict
    alias_result = try_alias_mapping(headers)
    if alias_result:
        upsert_mapping(supplier_id, alias_result, "alias", header_row, db, confidence=1.0)
        return alias_result, "alias", False

    # Tier 2 — LLM
    llm_result = await try_llm_mapping(headers, sample_rows)
    if llm_result:
        upsert_mapping(supplier_id, llm_result, "llm", header_row, db, confidence=0.85)
        return llm_result, "llm", False

    # Tier 3 — flag for human review
    # Build a partial mapping with whatever we can get from aliases
    partial: dict[str, str] = {}
    for header in headers:
        if not header:
            continue
        normalized = _normalize_header(header)
        if normalized in _REVERSE_ALIAS:
            canonical = _REVERSE_ALIAS[normalized]
            if canonical not in partial:
                partial[canonical] = header

    upsert_mapping(
        supplier_id, partial, "manual", header_row, db, needs_review=True
    )
    return partial, "manual", True
