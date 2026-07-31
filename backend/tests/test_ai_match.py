"""Tests for the suggest-only AI layer with mocked Anthropic client."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.reconciliation.ai_match import run_ai_suggestions
from app.reconciliation.exact_match import MatchCandidate, StatementItem


def _erp(erp_id=1, po="428759", material="MAT001", **kw):
    defaults = dict(
        quantity=Decimal("100"), po_price=Decimal("10.00"),
        amount=Decimal("1000.00"), grn_date=datetime(2026, 3, 15),
        delivery_note=None,
    )
    defaults.update(kw)
    return MatchCandidate(erp_id=erp_id, po_number=po, material_number=material, **defaults)


def _stmt(line_id=1, po="PO-428759", material="M-001", **kw):
    defaults = dict(
        quantity=Decimal("100"), unit_price=Decimal("10.00"),
        amount=Decimal("1000.00"), delivery_date=None,
        delivery_note_ref=None,
    )
    defaults.update(kw)
    return StatementItem(line_id=line_id, po_number=po, material_number=material, **defaults)


def _mock_response(matches_json: list[dict]) -> MagicMock:
    """Create a mock anthropic API response."""
    response = MagicMock()
    content = MagicMock()
    content.text = json.dumps(matches_json)
    response.content = [content]
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    return response


class TestAISuggestions:
    @pytest.mark.asyncio
    async def test_no_api_key_skips(self):
        """AI layer should gracefully skip when no API key."""
        suggestions = await run_ai_suggestions(
            [_erp()], [_stmt()], anthropic_api_key=None
        )
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_empty_inputs(self):
        suggestions = await run_ai_suggestions([], [], anthropic_api_key="test-key")
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_successful_suggestion(self):
        """AI returns a valid pairing hint — surfaced as a suggestion, not a match."""
        ai_response = [
            {"erp_index": 0, "stmt_index": 0, "confidence": 0.85, "reason": "PO format variant"}
        ]

        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_response(ai_response))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            suggestions = await run_ai_suggestions(
                [_erp(erp_id=7)], [_stmt(line_id=9)], anthropic_api_key="test-key"
            )

        assert len(suggestions) == 1
        assert suggestions[0]["erp_id"] == 7
        assert suggestions[0]["stmt_line_id"] == 9
        assert suggestions[0]["confidence"] == 0.85
        assert suggestions[0]["reason"] == "PO format variant"

    @pytest.mark.asyncio
    async def test_low_confidence_rejected(self):
        """Suggestions below 0.7 confidence should be dropped."""
        ai_response = [
            {"erp_index": 0, "stmt_index": 0, "confidence": 0.5, "reason": "weak match"}
        ]

        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_response(ai_response))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            suggestions = await run_ai_suggestions(
                [_erp()], [_stmt()], anthropic_api_key="test-key"
            )

        assert suggestions == []

    @pytest.mark.asyncio
    async def test_api_failure_graceful(self):
        """API errors should not crash — just return no suggestions."""
        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            suggestions = await run_ai_suggestions(
                [_erp()], [_stmt()], anthropic_api_key="test-key"
            )

        assert suggestions == []

    @pytest.mark.asyncio
    async def test_each_row_suggested_at_most_once(self):
        """Duplicate index pairs must not produce duplicate suggestions."""
        ai_response = [
            {"erp_index": 0, "stmt_index": 0, "confidence": 0.8, "reason": "first"},
            {"erp_index": 0, "stmt_index": 1, "confidence": 0.9, "reason": "dup erp"},
        ]

        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_response(ai_response))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            suggestions = await run_ai_suggestions(
                [_erp(erp_id=1)],
                [_stmt(line_id=1), _stmt(line_id=2)],
                anthropic_api_key="test-key",
            )

        assert len(suggestions) == 1
        assert suggestions[0]["reason"] == "first"
