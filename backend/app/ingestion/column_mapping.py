"""Three-tier column mapping: alias dict → LLM → human review.

Maps Chinese column headers from supplier statements to canonical field names
used by StatementLineItem.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.header_detection import clean_header_cells
from app.models import SupplierColumnMapping

logger = logging.getLogger(__name__)

# LLM mappings below this confidence are still applied but flagged for human
# review rather than trusted silently.
LLM_CONFIDENCE_REVIEW_THRESHOLD = 0.70

# How many leading rows to hand the LLM when it must locate the header row
# itself (deterministic keyword detection having failed).
LLM_HEADER_SCAN_ROWS = 15

_LLM_MODEL = "claude-haiku-4-5-20251001"

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
        "客户订单",
    ],
    "material_number": [
        "物料编码",
        "客户料号",
        "对应代码",
        "产品名称",
        "产品型号",
        "客户型号",
        "规格型号",
        "规格型号1",
    ],
    "quantity": [
        # Delivered-type (preferred) — reconciliation compares actual delivered
        # qty against ERP received qty, so these always beat ordered-type below
        # regardless of column order (see _resolve_quantity).
        "实发数量",
        "交货数量",
        "数量",
        "数量(PCS)",
        "数量(P)",
        "数量（P)",
        "数量(P",
        # Ordered-type (fallback) — used only when no delivered column exists.
        "订单数量",
        "订货数量",
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
        "总金额",
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

# Quantity headers that mean "ordered", not "delivered". Reconciliation
# compares delivered qty against ERP received qty, so a delivered-type column
# always wins when both are present; these are a fallback only.
_QUANTITY_ORDERED = {"订单数量", "订货数量"}


def _normalize_header(h: str) -> str:
    """Normalize a header string for alias lookup."""
    s = h.strip()
    # Full-width parens → half-width
    s = s.replace("（", "(").replace("）", ")")
    return s


# Guowei part number pattern: NNN*NNN+ (e.g. 126*1715*9*006, 590*5121*9*001)
_GUOWEI_PN_PATTERN = re.compile(r"\d{3}\*\d{3,}")


def _score_material_column(
    header: str, col_idx: int, sample_rows: list[list[str]] | None,
) -> float:
    """Score how likely a column contains Guowei part numbers (0.0–1.0).

    Checks sample data values against the known part number pattern.
    Returns 0.5 if no sample data is available (neutral score).
    """
    if not sample_rows:
        return 0.5
    hits = 0
    total = 0
    for row in sample_rows:
        if col_idx >= len(row):
            continue
        val = row[col_idx].strip()
        if not val:
            continue
        total += 1
        if _GUOWEI_PN_PATTERN.search(val):
            hits += 1
    return hits / total if total > 0 else 0.5


def try_alias_mapping(
    headers: list[str], sample_rows: list[list[str]] | None = None,
) -> dict[str, str] | None:
    """Tier 1: Try to map headers using the alias dictionary.

    When multiple columns match material_number aliases, validates against
    sample data to pick the column that contains actual part numbers
    (NNN*NNNN*N*NNN pattern) rather than supplier-internal codes.

    Returns:
        Dict mapping canonical field name → original column header,
        or None if required fields can't be mapped.
    """
    mapping: dict[str, str] = {}
    # Track all material_number candidates with their column indices
    material_candidates: list[tuple[str, int]] = []
    # Track quantity candidates with whether they are ordered-type (fallback).
    quantity_candidates: list[tuple[str, int, bool]] = []

    for idx, header in enumerate(headers):
        if not header:
            continue
        normalized = _normalize_header(header)
        if normalized in _REVERSE_ALIAS:
            canonical = _REVERSE_ALIAS[normalized]
            if canonical == "material_number":
                material_candidates.append((header, idx))
            elif canonical == "quantity":
                quantity_candidates.append(
                    (header, idx, normalized in _QUANTITY_ORDERED)
                )
            elif canonical not in mapping:
                mapping[canonical] = header

    # Resolve quantity: a delivered-type column always wins over an ordered-type
    # one, independent of column order (a statement often lists 订单数量 before
    # 交货数量, but reconciliation needs the delivered figure).
    if quantity_candidates:
        delivered = [c for c in quantity_candidates if not c[2]]
        chosen = delivered[0] if delivered else quantity_candidates[0]
        mapping["quantity"] = chosen[0]

    # Also check for unmapped columns whose data matches the part number pattern
    if sample_rows:
        mapped_headers = set(mapping.values())
        for idx, header in enumerate(headers):
            if not header or header in mapped_headers:
                continue
            if header in [h for h, _ in material_candidates]:
                continue
            score = _score_material_column(header, idx, sample_rows)
            if score >= 0.5:
                material_candidates.append((header, idx))

    # Pick the best material_number column by data validation
    if material_candidates:
        if len(material_candidates) == 1 and not sample_rows:
            mapping["material_number"] = material_candidates[0][0]
        else:
            best_header = None
            best_score = -1.0
            for header, idx in material_candidates:
                score = _score_material_column(header, idx, sample_rows)
                if score > best_score:
                    best_score = score
                    best_header = header
            if best_header is not None:
                mapping["material_number"] = best_header

    if REQUIRED_FIELDS.issubset(mapping.keys()):
        return mapping
    return None


def _anthropic_client():
    """Build an Anthropic client, or None if unconfigured/unavailable.

    A missing key is logged at ERROR, not silently ignored: without it, any
    unfamiliar statement format falls through to manual review, which is an
    operational problem worth surfacing — not normal behaviour.
    """
    if not settings.anthropic_api_key:
        logger.error(
            "No ANTHROPIC_API_KEY configured — cannot auto-map unfamiliar "
            "statement formats; they will require manual review."
        )
        return None
    try:
        import anthropic

        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception:
        logger.exception("Failed to initialize Anthropic client")
        return None


def _parse_json_response(text: str) -> Any:
    """Extract a JSON object from a model response (tolerates ``` fences)."""
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# Shared field guidance for the LLM prompts — kept in sync with ALIAS_MAP so the
# model and the deterministic path agree on what each canonical field means.
_MAPPING_FIELDS_DOC = """- po_number: Purchase order number (订单号/订单号码/客户订单/P.O.NO)
- material_number: Part/material code — usually a coded part number like 013*1696*2*003 (物料编码/料号/客户型号/规格型号), NOT a free-text product name
- quantity: Quantity actually delivered — prefer a delivered-qty column (交货数量/实发数量) over an ordered-qty column (订单数量)
- unit_price: Price per unit
- amount: Total line amount (price × quantity)
- delivery_date: Date of delivery
- delivery_note_ref: Delivery note reference number"""


def _validate_llm_map(
    column_map: dict[str, str],
    headers: list[str],
    sample_rows: list[list[str]] | None,
) -> dict[str, str] | None:
    """Validate an LLM-produced column map against the real headers.

    - Drops entries that aren't canonical fields or whose column isn't an actual
      header string.
    - Re-scores the chosen material_number column against the part-number
      pattern; if the model picked a free-text column over a coded one, swap to
      the coded column (mirrors the alias path's material validation).
    - Returns the validated map, or None if required fields are missing.
    """
    validated: dict[str, str] = {}
    for field, col_name in (column_map or {}).items():
        if (
            field in CANONICAL_FIELDS
            and isinstance(col_name, str)
            and col_name in headers
        ):
            validated[field] = col_name

    # Material re-validation: only override when the model's pick looks weak
    # (not a part number) AND a better, unmapped coded column is available.
    mat = validated.get("material_number")
    if sample_rows and mat in headers:
        if _score_material_column(mat, headers.index(mat), sample_rows) < 0.5:
            mapped = set(validated.values())
            for idx, h in enumerate(headers):
                if not h or h in mapped:
                    continue
                if _score_material_column(h, idx, sample_rows) >= 0.5:
                    validated["material_number"] = h
                    break

    if REQUIRED_FIELDS.issubset(validated.keys()):
        return validated
    logger.warning("LLM mapping missing required fields: %s", validated)
    return None


async def try_llm_mapping(
    headers: list[str], sample_rows: list[list[str]]
) -> tuple[dict[str, str], float] | None:
    """Tier 2: map already-detected headers via Claude.

    Returns (column_map, confidence), or None if unavailable or the mapping
    fails validation / misses required fields.
    """
    client = _anthropic_client()
    if client is None:
        return None

    prompt = f"""You are mapping Chinese column headers from a supplier reconciliation statement
to canonical field names.

The column headers are: {json.dumps(headers, ensure_ascii=False)}

Here are sample data rows:
{json.dumps(sample_rows, ensure_ascii=False)}

Map each header to one of these canonical fields (if applicable):
{_MAPPING_FIELDS_DOC}

Return ONLY a JSON object with "confidence" (0.0-1.0) and "column_map" (canonical
field -> exact header string):
{{"confidence": 0.9, "column_map": {{"po_number": "订单号", "quantity": "数量", "amount": "金额"}}}}
Only include fields you are confident about."""

    try:
        response = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        obj = _parse_json_response(response.content[0].text)
        validated = _validate_llm_map(obj.get("column_map", {}), headers, sample_rows)
        if validated is None:
            return None
        return validated, float(obj.get("confidence", 0.8))
    except Exception:
        logger.exception("LLM column mapping failed")
        return None


async def llm_detect_and_map(
    top_rows: list[list[str]],
) -> tuple[int, dict[str, str], float] | None:
    """Combined LLM header-row detection + column mapping.

    For layouts the deterministic keyword detector can't handle (e.g. an English
    ``P.O.NO`` header that lacks the 订单 keyword), ``detect_header_row`` raises
    before mapping is ever attempted — blocking the most general tool behind the
    most brittle one. This sends the top rows as an indexed grid and asks Claude
    for BOTH the header row index and the column map in a single call.

    Returns (header_row, column_map, confidence) or None.
    """
    client = _anthropic_client()
    if client is None:
        return None

    # Clean every cell so the header text the model returns matches what we
    # compare against downstream (full-width parens, stray newlines, etc.).
    grid = {
        i: clean_header_cells([str(v) for v in row])
        for i, row in enumerate(top_rows)
    }
    prompt = f"""You are analyzing a supplier reconciliation statement spreadsheet.
Below are the first rows as a JSON object of row_index -> cell values:
{json.dumps(grid, ensure_ascii=False)}

1. Identify the row index holding the COLUMN HEADERS (not the title, company, or
   address rows above it).
2. Map those headers to canonical field names:
{_MAPPING_FIELDS_DOC}

Return ONLY a JSON object:
{{"header_row": <int>, "confidence": <0.0-1.0>, "column_map": {{"po_number": "<exact header text>", ...}}}}
column_map values MUST be exact strings from the identified header row."""

    try:
        response = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        obj = _parse_json_response(response.content[0].text)
        header_row = int(obj["header_row"])
        if not (0 <= header_row < len(top_rows)):
            logger.warning("LLM returned out-of-range header_row %s", header_row)
            return None
        headers = grid[header_row]
        sample = [grid[i] for i in range(header_row + 1, min(header_row + 4, len(top_rows)))]
        validated = _validate_llm_map(obj.get("column_map", {}), headers, sample)
        if validated is None:
            return None
        return header_row, validated, float(obj.get("confidence", 0.8))
    except Exception:
        logger.exception("LLM header detection + mapping failed")
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
    # Tier 1 — alias dict (with sample data for material number validation)
    alias_result = try_alias_mapping(headers, sample_rows)
    if alias_result:
        upsert_mapping(supplier_id, alias_result, "alias", header_row, db, confidence=1.0)
        return alias_result, "alias", False

    # Tier 2 — LLM. Low-confidence results are still applied but flagged for
    # human review rather than trusted blindly.
    llm_result = await try_llm_mapping(headers, sample_rows)
    if llm_result:
        column_map, confidence = llm_result
        needs_review = confidence < LLM_CONFIDENCE_REVIEW_THRESHOLD
        upsert_mapping(
            supplier_id, column_map, "llm", header_row, db,
            confidence=confidence, needs_review=needs_review,
        )
        return column_map, "llm", needs_review

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
