"""Tests for invoice OCR extraction with mocked Anthropic client."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.invoicing.ocr_extractor import InvoiceExtractionResult, extract_invoice


def _mock_ocr_response(parsed: dict) -> MagicMock:
    """Create a mock anthropic API response containing JSON."""
    response = MagicMock()
    content = MagicMock()
    content.text = json.dumps(parsed)
    response.content = [content]
    response.usage = MagicMock()
    response.usage.input_tokens = 500
    response.usage.output_tokens = 300
    return response


_VALID_EXTRACTION = {
    "fields": {
        "supplier_name": "奥雄电子有限公司",
        "invoice_number": "12345678",
        "invoice_date": "2026-03-15",
        "subtotal": 10000.00,
        "vat_rate": 13,
        "vat_amount": 1300.00,
        "total_amount": 11300.00,
        "currency": "RMB",
    },
    "field_confidences": {
        "supplier_name": 0.95,
        "invoice_number": 0.98,
        "invoice_date": 0.92,
        "subtotal": 0.90,
        "vat_rate": 0.99,
        "vat_amount": 0.88,
        "total_amount": 0.93,
        "currency": 0.99,
    },
    "line_items": [
        {
            "description": "电容器 100uF",
            "quantity": 5000,
            "unit_price": 2.00,
            "amount": 10000.00,
            "po_number": "PO-428759",
            "material_number": None,
        }
    ],
}


def _make_temp_file(ext: str = "png", content: bytes = b"fake image data") -> str:
    """Create a temporary file with given extension."""
    f = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestExtractInvoice:
    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        """Full extraction with all fields above confidence threshold."""
        tmp = _make_temp_file("png")

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_ocr_response(_VALID_EXTRACTION)
            )
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "png", api_key="test-key")

        assert result.status == "success"
        assert result.fields["supplier_name"] == "奥雄电子有限公司"
        assert result.fields["invoice_number"] == "12345678"
        assert result.fields["total_amount"] == 11300.00
        assert result.overall_confidence == 0.88  # min of all confidences
        assert len(result.line_items) == 1
        assert result.line_items[0]["description"] == "电容器 100uF"
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_needs_review_low_confidence(self):
        """Extraction with some fields below 0.80 should flag needs_review."""
        extraction = {
            "fields": {
                "supplier_name": "某公司",
                "invoice_number": "???",
                "invoice_date": None,
                "subtotal": None,
                "vat_rate": None,
                "vat_amount": None,
                "total_amount": 5000.00,
                "currency": "RMB",
            },
            "field_confidences": {
                "supplier_name": 0.60,
                "invoice_number": 0.30,
                "invoice_date": 0.0,
                "subtotal": 0.0,
                "vat_rate": 0.0,
                "vat_amount": 0.0,
                "total_amount": 0.85,
                "currency": 0.99,
            },
            "line_items": [],
        }
        tmp = _make_temp_file("jpg")

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_ocr_response(extraction)
            )
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "jpg", api_key="test-key")

        assert result.status == "needs_review"
        assert result.overall_confidence == 0.0  # min includes 0.0 fields

    @pytest.mark.asyncio
    async def test_pdf_content_block(self):
        """PDF files should use document content block type."""
        tmp = _make_temp_file("pdf", content=b"%PDF-1.4 fake")

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_ocr_response(_VALID_EXTRACTION)
            )
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "pdf", api_key="test-key")

            # Verify the API was called with document type
            call_args = mock_client.messages.create.call_args
            content_blocks = call_args.kwargs["messages"][0]["content"]
            assert content_blocks[0]["type"] == "document"
            assert content_blocks[0]["source"]["media_type"] == "application/pdf"

        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_image_content_block(self):
        """Image files should use image content block type."""
        tmp = _make_temp_file("png")

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_ocr_response(_VALID_EXTRACTION)
            )
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            await extract_invoice(tmp, "png", api_key="test-key")

            call_args = mock_client.messages.create.call_args
            content_blocks = call_args.kwargs["messages"][0]["content"]
            assert content_blocks[0]["type"] == "image"
            assert content_blocks[0]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_malformed_json_response(self):
        """Malformed JSON from API should return error status."""
        tmp = _make_temp_file("png")

        response = MagicMock()
        content = MagicMock()
        content.text = "This is not valid JSON at all"
        response.content = [content]

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "png", api_key="test-key")

        assert result.status == "error"
        assert any("parse" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_markdown_code_block_response(self):
        """Response wrapped in ```json ... ``` should be parsed correctly."""
        tmp = _make_temp_file("png")

        response = MagicMock()
        content = MagicMock()
        content.text = "```json\n" + json.dumps(_VALID_EXTRACTION) + "\n```"
        response.content = [content]

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "png", api_key="test-key")

        assert result.status == "success"
        assert result.fields["invoice_number"] == "12345678"

    @pytest.mark.asyncio
    async def test_api_failure(self):
        """API exception should return error gracefully."""
        tmp = _make_temp_file("png")

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("Service unavailable"))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "png", api_key="test-key")

        assert result.status == "error"
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_unsupported_file_type(self):
        """Unsupported file types should return error."""
        result = await extract_invoice("/tmp/fake.bmp", "bmp", api_key="test-key")
        assert result.status == "error"
        assert any("Unsupported" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """Missing file should return error."""
        result = await extract_invoice("/nonexistent/path.png", "png", api_key="test-key")
        assert result.status == "error"
        assert any("not found" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_extraction_response(self):
        """Response with empty fields should still parse."""
        extraction = {
            "fields": {},
            "field_confidences": {},
            "line_items": [],
        }
        tmp = _make_temp_file("png")

        with patch("app.invoicing.ocr_extractor.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_ocr_response(extraction)
            )
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            result = await extract_invoice(tmp, "png", api_key="test-key")

        # No confidence values → overall = 0.0, no fields to be below threshold
        assert result.status == "success"
        assert result.overall_confidence == 0.0
        assert result.fields == {}
        assert result.line_items == []


class TestFileStorage:
    def test_save_and_retrieve(self):
        from app.invoicing.file_storage import get_file_path, save_upload

        with tempfile.TemporaryDirectory() as tmpdir:
            file_id, rel_path = save_upload(b"test content", "png", tmpdir)
            assert rel_path.endswith(".png")
            assert file_id in rel_path

            full_path = get_file_path(rel_path, tmpdir)
            assert Path(full_path).read_bytes() == b"test content"

    def test_creates_directory(self):
        from app.invoicing.file_storage import save_upload

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = str(Path(tmpdir) / "nested" / "dir")
            _, rel_path = save_upload(b"data", "pdf", nested)
            assert (Path(nested) / rel_path).exists()
