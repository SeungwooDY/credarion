"""Tests for the SGWERP GRN ingestion pipeline.

Tests column resolution, data normalization (VAT, currency, dates),
supplier upsert, and end-to-end ingestion against synthetic GRN data.
"""
from __future__ import annotations

import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import String, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.ingestion.cleaning import normalize_numeric, normalize_po_number, parse_date
from app.ingestion.grn_ingestor import (
    GRN_COLUMN_ALIASES,
    GRNIngestionResult,
    _parse_currency,
    _parse_vat_rate,
    _resolve_grn_columns,
    ingest_grn,
)
from app.models import ERPRecord, Organization, Supplier

# Path to GRN sample (may not exist — tests skip gracefully)
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "erp"
GRN_FILE = SAMPLES_DIR / "March Goods Receipt Detail.xlsx - GRN.csv"


# ============================================================
# Column Resolution
# ============================================================


class TestColumnResolution:
    def test_chinese_columns(self):
        cols = ["供应商编码", "供应商名称", "采购订单号", "物料编码", "收货数量",
                "采购单价", "金额", "币别", "税率", "收货单号", "收货日期", "送货单号"]
        result = _resolve_grn_columns(cols)
        assert result["vend_no"] == "供应商编码"
        assert result["po_number"] == "采购订单号"
        assert result["material_number"] == "物料编码"
        assert result["quantity"] == "收货数量"
        assert result["po_price"] == "采购单价"
        assert result["amount"] == "金额"
        assert result["currency"] == "币别"
        assert result["vat_rate"] == "税率"
        assert result["grn_number"] == "收货单号"
        assert result["grn_date"] == "收货日期"

    def test_english_columns(self):
        cols = ["vend_no", "vend_name", "po_number", "material_number",
                "quantity", "po_price", "amount", "currency", "vat_rate",
                "grn_number", "grn_date"]
        result = _resolve_grn_columns(cols)
        assert result["vend_no"] == "vend_no"
        assert result["po_number"] == "po_number"

    def test_alternate_chinese_columns(self):
        cols = ["供应商代码", "采购单号", "物料编号", "实收数量",
                "订单单价", "含税金额", "入库单号", "入库日期"]
        result = _resolve_grn_columns(cols)
        assert result["vend_no"] == "供应商代码"
        assert result["po_number"] == "采购单号"
        assert result["quantity"] == "实收数量"
        assert result["grn_number"] == "入库单号"
        assert result["grn_date"] == "入库日期"

    def test_missing_columns_detected(self):
        cols = ["供应商编码", "采购订单号"]  # Missing many required
        result = _resolve_grn_columns(cols)
        assert "quantity" not in result
        assert "grn_number" not in result

    def test_whitespace_in_columns_handled(self):
        cols = [" 供应商编码 ", "采购订单号"]
        result = _resolve_grn_columns(cols)
        assert result["vend_no"] == " 供应商编码 "  # Strip happens on lookup key


# ============================================================
# VAT Rate Parsing
# ============================================================


class TestVATRateParsing:
    def test_integer_string(self):
        assert _parse_vat_rate("13") == 13

    def test_with_percent_sign(self):
        assert _parse_vat_rate("13%") == 13

    def test_decimal_ratio(self):
        assert _parse_vat_rate("0.13") == 13

    def test_zero(self):
        assert _parse_vat_rate("0") == 0

    def test_none(self):
        assert _parse_vat_rate(None) is None
        assert _parse_vat_rate("") is None
        assert _parse_vat_rate(float("nan")) is None


# ============================================================
# Currency Parsing
# ============================================================


class TestCurrencyParsing:
    def test_rmb_variants(self):
        assert _parse_currency("RMB") == "RMB"
        assert _parse_currency("CNY") == "RMB"
        assert _parse_currency("人民币") == "RMB"

    def test_usd_variants(self):
        assert _parse_currency("USD") == "USD"
        assert _parse_currency("美元") == "USD"
        assert _parse_currency("美金") == "USD"

    def test_hkd_variants(self):
        assert _parse_currency("HKD") == "HKD"
        assert _parse_currency("港币") == "HKD"
        assert _parse_currency("港元") == "HKD"

    def test_default_to_rmb(self):
        assert _parse_currency(None) == "RMB"
        assert _parse_currency("") == "RMB"

    def test_case_insensitive(self):
        assert _parse_currency("rmb") == "RMB"
        assert _parse_currency("usd") == "USD"

    def test_unknown_3letter_passthrough(self):
        assert _parse_currency("EUR") == "EUR"


# ============================================================
# End-to-End with Synthetic Data
# ============================================================


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing.

    Registers type compilation hooks so PostgreSQL-specific types
    (JSONB, UUID) render correctly on SQLite.
    """
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

    # Register JSONB → JSON and UUID → VARCHAR for SQLite dialect
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    @compiles(PG_UUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):
        return "VARCHAR(36)"

    engine = create_engine("sqlite:///:memory:", echo=False)

    # SQLite doesn't natively handle Python uuid objects — register adapter
    import sqlite3
    sqlite3.register_adapter(uuid.UUID, lambda u: str(u))
    sqlite3.register_converter("UUID", lambda b: uuid.UUID(b.decode()))

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def org(db_session: Session) -> Organization:
    """Create a test organization."""
    o = Organization(name="Test Org", reporting_currency="RMB")
    db_session.add(o)
    db_session.commit()
    return o


def _make_grn_csv(rows: list[dict], path: str) -> str:
    """Write a synthetic GRN CSV file."""
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


class TestGRNIngestionE2E:
    def test_basic_ingestion(self, db_session: Session, org: Organization):
        """Ingest 3 rows from 2 suppliers, verify records and supplier creation."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "奥雄电子",
                "采购订单号": "428759",
                "物料编码": "ABC*1234*5*678",
                "收货数量": "100",
                "采购单价": "0.50",
                "金额": "50.00",
                "币别": "RMB",
                "税率": "13",
                "收货单号": "GRN-2026-001",
                "收货日期": "2026-03-05",
                "送货单号": "DN001",
            },
            {
                "供应商编码": "SDD201",
                "供应商名称": "奥雄电子",
                "采购订单号": "428760",
                "物料编码": "DEF*5678*9*012",
                "收货数量": "200",
                "采购单价": "1.20",
                "金额": "240.00",
                "币别": "RMB",
                "税率": "13",
                "收货单号": "GRN-2026-002",
                "收货日期": "2026-03-06",
                "送货单号": "DN002",
            },
            {
                "供应商编码": "SDD305",
                "供应商名称": "鹏诚信科技",
                "采购订单号": "429001",
                "物料编码": "XYZ*9999*1*100",
                "收货数量": "10,000",
                "采购单价": "0.0433",
                "金额": "433.00",
                "币别": "USD",
                "税率": "0",
                "收货单号": "GRN-2026-003",
                "收货日期": "2026/3/10",
                "送货单号": "",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "success"
        assert result.rows_ingested == 3
        assert result.rows_skipped == 0

        # Verify suppliers created
        suppliers = db_session.query(Supplier).filter_by(org_id=org.id).all()
        assert len(suppliers) == 2
        vendor_codes = {s.vendor_code for s in suppliers}
        assert vendor_codes == {"SDD201", "SDD305"}

        # Verify ERP records
        records = db_session.query(ERPRecord).filter_by(org_id=org.id).all()
        assert len(records) == 3

        # Check specific record values
        rec_428759 = next(r for r in records if r.po_number == "428759")
        assert rec_428759.material_number == "ABC*1234*5*678"
        assert rec_428759.quantity == Decimal("100")
        assert rec_428759.po_price == Decimal("0.50") or rec_428759.po_price == Decimal("0.5000")
        assert rec_428759.currency == "RMB"
        assert rec_428759.vat_rate == 13
        assert rec_428759.grn_number == "GRN-2026-001"
        assert rec_428759.grn_date.year == 2026
        assert rec_428759.grn_date.month == 3
        assert rec_428759.grn_date.day == 5

        # Check USD supplier
        rec_usd = next(r for r in records if r.po_number == "429001")
        assert rec_usd.currency == "USD"
        assert rec_usd.quantity == Decimal("10000")
        assert rec_usd.vat_rate == 0

    def test_po_number_float_normalization(self, db_session: Session, org: Organization):
        """PO numbers like '428759.0' should become '428759'."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "Test",
                "采购订单号": "428759.0",
                "物料编码": "ABC*1234*5*678",
                "收货数量": "100",
                "采购单价": "1.00",
                "金额": "100.00",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "success"
        rec = db_session.query(ERPRecord).first()
        assert rec.po_number == "428759"

    def test_vat_rate_decimal_conversion(self, db_session: Session, org: Organization):
        """VAT rate '0.13' should become 13."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "Test",
                "采购订单号": "500001",
                "物料编码": "MAT001",
                "收货数量": "50",
                "采购单价": "2.00",
                "金额": "100.00",
                "税率": "0.13",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "success"
        rec = db_session.query(ERPRecord).first()
        assert rec.vat_rate == 13

    def test_missing_required_fields_skipped(self, db_session: Session, org: Organization):
        """Rows with missing po_number or quantity should be skipped."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "Test",
                "采购订单号": "",
                "物料编码": "MAT001",
                "收货数量": "50",
                "采购单价": "2.00",
                "金额": "100.00",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
            {
                "供应商编码": "SDD201",
                "供应商名称": "Test",
                "采购订单号": "500001",
                "物料编码": "MAT001",
                "收货数量": "",
                "采购单价": "2.00",
                "金额": "100.00",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
            {
                "供应商编码": "SDD201",
                "供应商名称": "Test",
                "采购订单号": "500002",
                "物料编码": "MAT002",
                "收货数量": "10",
                "采购单价": "5.00",
                "金额": "50.00",
                "收货单号": "GRN-002",
                "收货日期": "2026-03-06",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "success"
        assert result.rows_ingested == 1
        assert result.rows_skipped == 2

    def test_raw_row_preserved(self, db_session: Session, org: Organization):
        """raw_row JSONB should preserve all original column values."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "奥雄",
                "采购订单号": "428759",
                "物料编码": "ABC*1234",
                "收货数量": "100",
                "采购单价": "0.50",
                "金额": "50.00",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
                "ExtraColumn": "should_be_preserved",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "success"
        rec = db_session.query(ERPRecord).first()
        assert rec.raw_row["供应商编码"] == "SDD201"
        assert rec.raw_row["ExtraColumn"] == "should_be_preserved"

    def test_supplier_upsert_no_duplicates(self, db_session: Session, org: Organization):
        """Second ingestion should not create duplicate suppliers."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "奥雄",
                "采购订单号": "428759",
                "物料编码": "MAT001",
                "收货数量": "100",
                "采购单价": "1.00",
                "金额": "100.00",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)

        # Ingest twice
        ingest_grn(tmp_path, org.id, db_session)
        ingest_grn(tmp_path, org.id, db_session)

        suppliers = db_session.query(Supplier).filter_by(org_id=org.id).all()
        assert len(suppliers) == 1

    def test_invalid_org_id(self, db_session: Session):
        """Ingestion with nonexistent org_id should fail."""
        rows = [
            {
                "供应商编码": "SDD201",
                "供应商名称": "Test",
                "采购订单号": "428759",
                "物料编码": "MAT001",
                "收货数量": "100",
                "采购单价": "1.00",
                "金额": "100.00",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        fake_org = uuid.uuid4()
        result = ingest_grn(tmp_path, fake_org, db_session)

        assert result.status == "error"
        assert any("not found" in e for e in result.errors)

    def test_missing_column_mapping_fails(self, db_session: Session, org: Organization):
        """File with unrecognized columns should fail with informative error."""
        rows = [{"col_a": "1", "col_b": "2"}]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "error"
        assert any("Could not map required columns" in e for e in result.errors)

    def test_cross_border_currency_detection(self, db_session: Session, org: Organization):
        """USD and HKD suppliers should have correct currency on records."""
        rows = [
            {
                "供应商编码": "USD001",
                "供应商名称": "US Supplier",
                "采购订单号": "600001",
                "物料编码": "MAT001",
                "收货数量": "50",
                "采购单价": "10.00",
                "金额": "500.00",
                "币别": "美元",
                "收货单号": "GRN-001",
                "收货日期": "2026-03-05",
            },
            {
                "供应商编码": "HKD001",
                "供应商名称": "HK Supplier",
                "采购订单号": "600002",
                "物料编码": "MAT002",
                "收货数量": "30",
                "采购单价": "20.00",
                "金额": "600.00",
                "币别": "港币",
                "收货单号": "GRN-002",
                "收货日期": "2026-03-06",
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name

        _make_grn_csv(rows, tmp_path)
        result = ingest_grn(tmp_path, org.id, db_session)

        assert result.status == "success"
        records = db_session.query(ERPRecord).all()
        currencies = {r.po_number: r.currency for r in records}
        assert currencies["600001"] == "USD"
        assert currencies["600002"] == "HKD"


# ============================================================
# Real GRN File (skipped if data not present)
# ============================================================


class TestRealGRNFile:
    @pytest.mark.skipif(not GRN_FILE.exists(), reason="GRN sample file not present")
    def test_column_resolution_on_real_file(self):
        """Verify column resolution works on the actual SGWERP export."""
        df = pd.read_csv(GRN_FILE, nrows=0, dtype=str)
        col_map = _resolve_grn_columns(list(df.columns))
        required = ["po_number", "material_number", "quantity", "po_price",
                     "amount", "grn_number", "grn_date"]
        missing = [f for f in required if f not in col_map]
        assert not missing, f"Missing required columns: {missing}. Found: {col_map}"

    @pytest.mark.skipif(not GRN_FILE.exists(), reason="GRN sample file not present")
    def test_real_file_row_count(self):
        """The GRN file should have ~6,648 rows."""
        df = pd.read_csv(GRN_FILE, dtype=str)
        assert len(df) > 6000, f"Expected ~6648 rows, got {len(df)}"

    @pytest.mark.skipif(not GRN_FILE.exists(), reason="GRN sample file not present")
    def test_real_file_ingestion(self, db_session: Session, org: Organization):
        """Full end-to-end ingestion of the real GRN file."""
        result = ingest_grn(str(GRN_FILE), org.id, db_session)
        assert result.status == "success"
        assert result.rows_ingested > 6000
        # Should have created ~214 suppliers
        suppliers = db_session.query(Supplier).filter_by(org_id=org.id).count()
        assert suppliers > 100
