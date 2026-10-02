"""Tests for the LLM-assisted header detection + column mapping (mocked LLM).

Covers the 2026-10-01 generalization work: the LLM now locates the header row
AND maps columns in one call when the deterministic keyword detector fails
(e.g. an English `P.O.NO` header), validates its own output against the
part-number pattern, and gates low-confidence results to human review.

No live API calls — the Anthropic client is always mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import app.ingestion.column_mapping as cm


def _fake_client(payload: dict) -> MagicMock:
    """A fake Anthropic client whose messages.create returns `payload` as JSON."""
    client = MagicMock()
    content = MagicMock()
    content.text = json.dumps(payload, ensure_ascii=False)
    response = MagicMock()
    response.content = [content]
    client.messages.create.return_value = response
    return client


# 国昌荣 (136) style: title rows, then an English "P.O.NO" header that lacks the
# 订单 keyword — so detect_header_row raises and the LLM must take over.
_GUOCHANGRONG_ROWS = [
    ["中山国昌荣电子有限公司", "", "", "", "", "", "", ""],
    ["对帐单(2026年7月份)", "", "", "", "", "", "", ""],
    ["送货日期", "送货单号", "P.O.NO", "品名", "规格型号", "数量", "单价", "金额"],
    ["6月26日", "20260626001", "431873", "线路板", "011*2662*4*003", "40800", "1.4", "57120"],
    ["6月26日", "20260626002", "431569", "线路板", "011*2347*4*003", "1616", "3.37", "5445"],
]


class TestLLMDetectAndMap:
    @pytest.mark.asyncio
    async def test_english_header_detected_and_mapped(self):
        payload = {
            "header_row": 2,
            "confidence": 0.9,
            "column_map": {
                "po_number": "P.O.NO",
                "quantity": "数量",
                "amount": "金额",
                "material_number": "规格型号",
                "unit_price": "单价",
                "delivery_date": "送货日期",
                "delivery_note_ref": "送货单号",
            },
        }
        with patch.object(cm, "_anthropic_client", return_value=_fake_client(payload)):
            result = await cm.llm_detect_and_map(_GUOCHANGRONG_ROWS)
        assert result is not None
        header_row, column_map, confidence = result
        assert header_row == 2
        assert column_map["po_number"] == "P.O.NO"
        assert column_map["quantity"] == "数量"
        assert column_map["amount"] == "金额"
        assert column_map["material_number"] == "规格型号"
        assert confidence == 0.9

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        with patch.object(cm, "_anthropic_client", return_value=None):
            result = await cm.llm_detect_and_map(_GUOCHANGRONG_ROWS)
        assert result is None

    @pytest.mark.asyncio
    async def test_out_of_range_header_row_rejected(self):
        payload = {"header_row": 99, "confidence": 0.9, "column_map": {}}
        with patch.object(cm, "_anthropic_client", return_value=_fake_client(payload)):
            result = await cm.llm_detect_and_map(_GUOCHANGRONG_ROWS)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_fields_rejected(self):
        payload = {
            "header_row": 2,
            "confidence": 0.9,
            "column_map": {"material_number": "规格型号"},  # no po/qty/amount
        }
        with patch.object(cm, "_anthropic_client", return_value=_fake_client(payload)):
            result = await cm.llm_detect_and_map(_GUOCHANGRONG_ROWS)
        assert result is None


class TestTryLLMMapping:
    @pytest.mark.asyncio
    async def test_returns_map_and_confidence(self):
        headers = ["订单号码", "料号", "数量", "金额"]
        sample = [["432701", "420*0065*3*000", "4000", "31.6"]]
        payload = {
            "confidence": 0.55,
            "column_map": {
                "po_number": "订单号码",
                "quantity": "数量",
                "amount": "金额",
                "material_number": "料号",
            },
        }
        with patch.object(cm, "_anthropic_client", return_value=_fake_client(payload)):
            result = await cm.try_llm_mapping(headers, sample)
        assert result is not None
        column_map, confidence = result
        assert confidence == 0.55
        assert column_map["po_number"] == "订单号码"


class TestValidateLLMMap:
    def test_prefers_coded_material_over_free_text(self):
        """The model sometimes picks a free-text name over a coded part number."""
        headers = ["订单号", "名称", "物料编号", "数量", "金额"]
        sample = [["431873", "普通箱", "013*1696*2*003", "100", "100"]]
        bad_map = {
            "po_number": "订单号",
            "material_number": "名称",  # free text — should be overridden
            "quantity": "数量",
            "amount": "金额",
        }
        out = cm._validate_llm_map(bad_map, headers, sample)
        assert out is not None
        assert out["material_number"] == "物料编号"

    def test_drops_columns_not_in_headers(self):
        headers = ["订单号", "数量", "金额"]
        out = cm._validate_llm_map(
            {"po_number": "订单号", "quantity": "数量", "amount": "金额",
             "material_number": "nonexistent"},
            headers,
            None,
        )
        assert out is not None
        assert "material_number" not in out

    def test_returns_none_when_required_missing(self):
        headers = ["名称", "单价"]
        out = cm._validate_llm_map({"unit_price": "单价"}, headers, None)
        assert out is None
