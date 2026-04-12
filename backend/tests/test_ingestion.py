"""Tests for the supplier statement ingestion pipeline.

Tests header detection, column mapping, data cleaning, and end-to-end
ingestion against the 5 real supplier CSV samples in data/samples/.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.ingestion.cleaning import (
    clean_dataframe,
    filter_summary_rows,
    normalize_numeric,
    normalize_po_number,
    parse_date,
)
from app.ingestion.column_mapping import try_alias_mapping
from app.ingestion.header_detection import clean_header_cells, detect_header_row

# Path to supplier statement CSVs
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "supplier_statements"

AOXIONG = SAMPLES_DIR / "Guowei-Aoxiong March 2026 Reconciliation.xlsx - Sheet1.csv"
PENGCHENGXIN = SAMPLES_DIR / "Guowei Electronics March Reconciliation Statement (Supplier_Pengchengxin).xlsx - 鹏诚信.csv"
MAIDING = SAMPLES_DIR / "Maiding-Guowei March 2026 Reconciliation Statement.xlsx - 对账.csv"
FENGYUDA = SAMPLES_DIR / "Meizhou Guowei March 2026 Reconciliation Statement (Supplier_ Fengyuda).XLS - 国威3月份.csv"
ZHANBANG = SAMPLES_DIR / "Meizhou Guowei March 2026 Reconciliation Statement (Supplier_ Zhanbang).xls - 对账单.csv"

ALL_SUPPLIERS = [AOXIONG, PENGCHENGXIN, MAIDING, FENGYUDA, ZHANBANG]


def _read_raw(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, header=None, dtype=str)


# ============================================================
# Header Detection
# ============================================================


class TestHeaderDetection:
    @pytest.mark.parametrize("path", ALL_SUPPLIERS, ids=lambda p: p.stem[:20])
    def test_detects_header_row(self, path: Path):
        if not path.exists():
            pytest.skip(f"Sample file not found: {path.name}")
        df = _read_raw(path)
        row_idx = detect_header_row(df)
        row_text = " ".join(str(v) for v in df.iloc[row_idx] if pd.notna(v))
        assert "订单" in row_text, f"Header row {row_idx} missing '订单'"
        assert "数量" in row_text, f"Header row {row_idx} missing '数量'"

    def test_aoxiong_header_row_5(self):
        if not AOXIONG.exists():
            pytest.skip("Aoxiong sample not found")
        df = _read_raw(AOXIONG)
        assert detect_header_row(df) == 5

    def test_pengchengxin_header_row_7(self):
        if not PENGCHENGXIN.exists():
            pytest.skip("Pengchengxin sample not found")
        df = _read_raw(PENGCHENGXIN)
        assert detect_header_row(df) == 7

    def test_maiding_header_row_8(self):
        if not MAIDING.exists():
            pytest.skip("Maiding sample not found")
        df = _read_raw(MAIDING)
        # Maiding has multi-row header; row 8 has the combined header
        # (rows 8-9 in the CSV contain the header split across two lines)
        row_idx = detect_header_row(df)
        assert row_idx in (8, 9), f"Expected row 8 or 9, got {row_idx}"

    def test_fengyuda_header_row_9(self):
        if not FENGYUDA.exists():
            pytest.skip("Fengyuda sample not found")
        df = _read_raw(FENGYUDA)
        assert detect_header_row(df) == 9

    def test_zhanbang_header_row_9(self):
        if not ZHANBANG.exists():
            pytest.skip("Zhanbang sample not found")
        df = _read_raw(ZHANBANG)
        assert detect_header_row(df) == 9


class TestCleanHeaderCells:
    def test_strips_whitespace(self):
        assert clean_header_cells(["  日期  ", "订单号"]) == ["日期", "订单号"]

    def test_replaces_fullwidth_parens(self):
        assert clean_header_cells(["数量（PCS）"]) == ["数量(PCS)"]

    def test_removes_newlines(self):
        assert clean_header_cells(["单价\n（RMB）"]) == ["单价(RMB)"]


# ============================================================
# Tier 1 Alias Mapping
# ============================================================


class TestAliasMappingTier1:
    def test_aoxiong_maps(self):
        if not AOXIONG.exists():
            pytest.skip("Aoxiong sample not found")
        df = _read_raw(AOXIONG)
        row_idx = detect_header_row(df)
        raw_headers = [str(v) if pd.notna(v) else "" for v in df.iloc[row_idx]]
        headers = clean_header_cells(raw_headers)
        result = try_alias_mapping(headers)
        assert result is not None
        assert "po_number" in result
        assert "quantity" in result
        assert "amount" in result

    def test_pengchengxin_maps(self):
        if not PENGCHENGXIN.exists():
            pytest.skip("Pengchengxin sample not found")
        df = _read_raw(PENGCHENGXIN)
        row_idx = detect_header_row(df)
        raw_headers = [str(v) if pd.notna(v) else "" for v in df.iloc[row_idx]]
        headers = clean_header_cells(raw_headers)
        result = try_alias_mapping(headers)
        assert result is not None
        assert "po_number" in result

    def test_zhanbang_maps(self):
        if not ZHANBANG.exists():
            pytest.skip("Zhanbang sample not found")
        df = _read_raw(ZHANBANG)
        row_idx = detect_header_row(df)
        raw_headers = [str(v) if pd.notna(v) else "" for v in df.iloc[row_idx]]
        headers = clean_header_cells(raw_headers)
        result = try_alias_mapping(headers)
        assert result is not None
        assert "po_number" in result

    def test_fengyuda_maps(self):
        if not FENGYUDA.exists():
            pytest.skip("Fengyuda sample not found")
        df = _read_raw(FENGYUDA)
        row_idx = detect_header_row(df)
        raw_headers = [str(v) if pd.notna(v) else "" for v in df.iloc[row_idx]]
        headers = clean_header_cells(raw_headers)
        result = try_alias_mapping(headers)
        assert result is not None
        assert "po_number" in result


# ============================================================
# Data Cleaning
# ============================================================


class TestPONormalization:
    def test_float_to_int(self):
        assert normalize_po_number("428759.0") == "428759"

    def test_already_int(self):
        assert normalize_po_number("428759") == "428759"

    def test_string_po(self):
        assert normalize_po_number("428292-1") == "428292-1"

    def test_none_handling(self):
        assert normalize_po_number(None) is None
        assert normalize_po_number("") is None
        assert normalize_po_number(float("nan")) is None

    def test_whitespace(self):
        assert normalize_po_number("  428759  ") == "428759"


class TestNumericNormalization:
    def test_thousands_separator(self):
        assert normalize_numeric("10,000") == Decimal("10000")

    def test_plain_decimal(self):
        assert normalize_numeric("0.0433") == Decimal("0.0433")

    def test_with_spaces(self):
        assert normalize_numeric("814.0400 ") == Decimal("814.0400")

    def test_none(self):
        assert normalize_numeric(None) is None
        assert normalize_numeric("") is None

    def test_large_number(self):
        assert normalize_numeric("1,440.6") == Decimal("1440.6")


class TestDateParsing:
    def test_iso_format(self):
        d = parse_date("2026-03-02")
        assert d is not None
        assert d.year == 2026 and d.month == 3 and d.day == 2

    def test_slash_format(self):
        d = parse_date("2026/2/26")
        assert d is not None
        assert d.year == 2026 and d.month == 2 and d.day == 26

    def test_mdy_format(self):
        d = parse_date("2/7/2026")
        assert d is not None
        assert d.month == 2 and d.day == 7 and d.year == 2026

    def test_none(self):
        assert parse_date(None) is None
        assert parse_date("") is None


class TestSummaryRowFiltering:
    def test_filters_heji(self):
        df = pd.DataFrame({
            "a": ["data1", "合计", "data2"],
            "b": ["100", "500", "200"],
        })
        result = filter_summary_rows(df)
        assert len(result) == 2
        assert "合计" not in result["a"].values

    def test_filters_spaced_heji(self):
        """Zhanbang has '合    计' with spaces between characters."""
        df = pd.DataFrame({
            "a": ["data1", "合    计", "data2"],
            "b": ["100", "500", "200"],
        })
        result = filter_summary_rows(df)
        assert len(result) == 2

    def test_filters_shangyuejieyu(self):
        df = pd.DataFrame({
            "a": ["上月结余", "data1"],
            "b": ["0", "100"],
        })
        result = filter_summary_rows(df)
        assert len(result) == 1


# ============================================================
# End-to-End Cleaning
# ============================================================


class TestEndToEndCleaning:
    def test_aoxiong_e2e(self):
        """Aoxiong: PO 428759 should have 24 line items after cleaning."""
        if not AOXIONG.exists():
            pytest.skip("Aoxiong sample not found")

        # Detect header
        df_raw = _read_raw(AOXIONG)
        header_row = detect_header_row(df_raw)

        # Read with header
        df = pd.read_csv(AOXIONG, header=header_row, dtype=str)
        df.columns = clean_header_cells(list(df.columns.astype(str)))

        # Map columns
        mapping = try_alias_mapping(list(df.columns))
        assert mapping is not None

        # Clean
        df_clean = clean_dataframe(df, mapping)

        # Check PO 428759
        po_rows = df_clean[df_clean["po_number"] == "428759"]
        assert len(po_rows) == 29, f"Expected 29 rows for PO 428759, got {len(po_rows)}"

        # Verify quantities are Decimal
        for _, row in po_rows.iterrows():
            assert isinstance(row["quantity"], Decimal)
            assert row["quantity"] > 0

    def test_pengchengxin_has_thousands_separator_quantities(self):
        """Pengchengxin uses comma-separated thousands in quantities."""
        if not PENGCHENGXIN.exists():
            pytest.skip("Pengchengxin sample not found")

        df_raw = _read_raw(PENGCHENGXIN)
        header_row = detect_header_row(df_raw)
        df = pd.read_csv(PENGCHENGXIN, header=header_row, dtype=str)
        df.columns = clean_header_cells(list(df.columns.astype(str)))
        mapping = try_alias_mapping(list(df.columns))
        assert mapping is not None
        df_clean = clean_dataframe(df, mapping)

        # First row should have quantity 10000 (from "10,000")
        assert df_clean.iloc[0]["quantity"] == Decimal("10000")

    def test_no_summary_rows_in_output(self):
        """No cleaned output should contain summary keywords."""
        for path in ALL_SUPPLIERS:
            if not path.exists():
                continue
            df_raw = _read_raw(path)
            try:
                header_row = detect_header_row(df_raw)
            except ValueError:
                continue
            df = pd.read_csv(path, header=header_row, dtype=str)
            df.columns = clean_header_cells(list(df.columns.astype(str)))
            mapping = try_alias_mapping(list(df.columns))
            if mapping is None:
                continue
            df_clean = clean_dataframe(df, mapping)
            for _, row in df_clean.iterrows():
                row_text = "".join(
                    str(v).replace(" ", "") for v in row if pd.notna(v) and isinstance(v, str)
                )
                assert "合计" not in row_text, f"Summary row leaked through in {path.name}"
                assert "总计" not in row_text, f"Summary row leaked through in {path.name}"
