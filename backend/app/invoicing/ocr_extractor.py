"""Core OCR extraction using Claude Vision API for fapiao processing."""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an invoice data extraction assistant specializing in Chinese fapiao (发票).
You process both 增值税专用发票 (VAT special invoices) and 增值税普通发票 (VAT ordinary invoices).

Extract the following fields from the invoice image/document. For each field, provide your confidence
score (0.0 to 1.0) indicating how certain you are about the extracted value.

Return a JSON object with exactly this structure:
{
  "fields": {
    "supplier_name": "<supplier/seller name>",
    "invoice_number": "<invoice number / 发票号码>",
    "invoice_date": "<YYYY-MM-DD>",
    "subtotal": <number or null>,
    "vat_rate": <percentage as number e.g. 13 for 13%, or null>,
    "vat_amount": <number or null>,
    "total_amount": <number or null>,
    "currency": "<3-letter code, default RMB>"
  },
  "field_confidences": {
    "supplier_name": <0.0-1.0>,
    "invoice_number": <0.0-1.0>,
    "invoice_date": <0.0-1.0>,
    "subtotal": <0.0-1.0>,
    "vat_rate": <0.0-1.0>,
    "vat_amount": <0.0-1.0>,
    "total_amount": <0.0-1.0>,
    "currency": <0.0-1.0>
  },
  "line_items": [
    {
      "description": "<item description>",
      "quantity": <number or null>,
      "unit_price": <number or null>,
      "amount": <number or null>,
      "po_number": "<PO number if visible, else null>",
      "material_number": "<material/part number if visible, else null>"
    }
  ]
}

Rules:
- If a field is not visible or illegible, set its value to null and confidence to 0.0
- Dates must be in YYYY-MM-DD format
- Monetary amounts should be numbers without currency symbols
- VAT rate should be a percentage number (e.g., 13 not 0.13)
- Return ONLY the JSON object, no other text"""


@dataclass
class InvoiceExtractionResult:
    status: str  # "success" | "needs_review" | "error"
    fields: dict[str, Any] = field(default_factory=dict)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    field_confidences: dict[str, float] = field(default_factory=dict)
    overall_confidence: float = 0.0
    raw_response: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


def _build_content_block(file_bytes: bytes, file_type: str, media_type: str) -> dict[str, Any]:
    """Build the appropriate content block for the Claude API."""
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

    if file_type == "pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": b64,
            },
        }
    else:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64,
            },
        }


_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
}


async def extract_invoice(
    file_path: str,
    file_type: str,
    api_key: str,
    model: str = "claude-haiku-4-5-20251001",
) -> InvoiceExtractionResult:
    """Extract structured data from an invoice image or PDF using Claude Vision API."""
    ext = file_type.lower().lstrip(".")
    media_type = _MEDIA_TYPES.get(ext)
    if not media_type:
        return InvoiceExtractionResult(
            status="error",
            errors=[f"Unsupported file type: {file_type}"],
        )

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except FileNotFoundError:
        return InvoiceExtractionResult(
            status="error",
            errors=[f"File not found: {file_path}"],
        )

    content_block = _build_content_block(file_bytes, ext, media_type)

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        content_block,
                        {"type": "text", "text": "Extract all fields from this invoice."},
                    ],
                }
            ],
        )
    except Exception as e:
        logger.warning("OCR API call failed: %s", e)
        return InvoiceExtractionResult(
            status="error",
            errors=[f"API call failed: {e}"],
        )

    # Parse response
    try:
        text = response.content[0].text.strip()
        # Extract JSON from potential markdown code blocks
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        parsed = json.loads(text)
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        logger.warning("Failed to parse OCR response: %s", e)
        return InvoiceExtractionResult(
            status="error",
            errors=[f"Failed to parse response: {e}"],
            raw_response={"raw_text": response.content[0].text if response.content else ""},
        )

    fields = parsed.get("fields", {})
    field_confidences = parsed.get("field_confidences", {})
    line_items = parsed.get("line_items", [])

    # Compute overall confidence as minimum of all field confidences
    confidence_values = [v for v in field_confidences.values() if isinstance(v, (int, float))]
    overall_confidence = min(confidence_values) if confidence_values else 0.0

    needs_review = any(c < 0.80 for c in confidence_values)
    status = "needs_review" if needs_review else "success"

    return InvoiceExtractionResult(
        status=status,
        fields=fields,
        line_items=line_items,
        field_confidences=field_confidences,
        overall_confidence=overall_confidence,
        raw_response=parsed,
    )
