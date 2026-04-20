"""Tests for Layer 4: AI matching with mocked Anthropic client."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.reconciliation.ai_match import run_ai_match
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


class TestAIMatch:
    @pytest.mark.asyncio
    async def test_no_api_key_skips(self):
        """AI layer should gracefully skip when no API key."""
        erp = [_erp()]
        stmt = [_stmt()]
        matches, unmatched_erp, unmatched_stmt = await run_ai_match(
            erp, stmt, anthropic_api_key=None
        )
        assert len(matches) == 0
        assert len(unmatched_erp) == 1
        assert len(unmatched_stmt) == 1

    @pytest.mark.asyncio
    async def test_empty_inputs(self):
        matches, _, _ = await run_ai_match([], [], anthropic_api_key="test-key")
        assert len(matches) == 0

    @pytest.mark.asyncio
    async def test_successful_ai_match(self):
        """AI returns a valid match with high confidence."""
        ai_response = [
            {"erp_index": 0, "stmt_index": 0, "confidence": 0.85, "reason": "PO format variant"}
        ]

        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_response(ai_response))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            erp = [_erp()]
            stmt = [_stmt()]
            matches, unmatched_erp, unmatched_stmt = await run_ai_match(
                erp, stmt, anthropic_api_key="test-key"
            )

        assert len(matches) == 1
        assert matches[0].match_type == "ai"
        assert matches[0].confidence == Decimal("0.85")
        assert len(unmatched_erp) == 0
        assert len(unmatched_stmt) == 0

    @pytest.mark.asyncio
    async def test_low_confidence_rejected(self):
        """Matches below 0.7 confidence should be rejected."""
        ai_response = [
            {"erp_index": 0, "stmt_index": 0, "confidence": 0.5, "reason": "weak match"}
        ]

        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_response(ai_response))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            matches, unmatched_erp, unmatched_stmt = await run_ai_match(
                [_erp()], [_stmt()], anthropic_api_key="test-key"
            )

        assert len(matches) == 0
        assert len(unmatched_erp) == 1

    @pytest.mark.asyncio
    async def test_api_failure_graceful(self):
        """API errors should not crash — just return all items as unmatched."""
        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            matches, unmatched_erp, unmatched_stmt = await run_ai_match(
                [_erp()], [_stmt()], anthropic_api_key="test-key"
            )

        assert len(matches) == 0
        assert len(unmatched_erp) == 1
        assert len(unmatched_stmt) == 1

    @pytest.mark.asyncio
    async def test_discrepancy_detected(self):
        """AI match with qty difference should flag discrepancy."""
        ai_response = [
            {"erp_index": 0, "stmt_index": 0, "confidence": 0.80, "reason": "same PO"}
        ]

        with patch("app.reconciliation.ai_match.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_response(ai_response))
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            erp = [_erp(quantity=Decimal("100"))]
            stmt = [_stmt(quantity=Decimal("120"))]
            matches, _, _ = await run_ai_match(
                erp, stmt, anthropic_api_key="test-key"
            )

        assert len(matches) == 1
        assert matches[0].status == "discrepancy"
        assert matches[0].discrepancy_type == "quantity_over"
