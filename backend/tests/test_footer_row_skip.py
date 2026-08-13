"""Statement ingestion skips identifier-less total/footer rows.

Supplier statements end with a 合计 row carrying the grand totals (qty +
amount) and nothing else. Before the guard, SDD201's footer ingested as a
phantom qty-2,130,601 "not in ERP" claim. A real line always names a PO or a
material; rows with neither are dropped and counted as skipped.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.ingestion.statement_ingestor import ingest_supplier_statement
from app.models import Organization, StatementLineItem, Supplier, SupplierColumnMapping

from tests.role_helpers import make_sqlite_session

CSV = """订单单号(PO),产品名称(PN),实发数量,销售单价,销售金额,日期,单据编号
428001,590*0001*0*001,100,1.5,150,2026-03-05,DN001
428001,590*0002*0*001,200,2.0,400,2026-03-06,DN002
,,2130601,,147060.88,,
"""

COLUMN_MAP = {
    "po_number": "订单单号(PO)",
    "material_number": "产品名称(PN)",
    "quantity": "实发数量",
    "unit_price": "销售单价",
    "amount": "销售金额",
    "delivery_date": "日期",
    "delivery_note_ref": "单据编号",
}


@pytest.fixture
def db_session():
    session = make_sqlite_session()
    yield session
    session.close()


def test_total_footer_row_is_skipped(db_session):
    org = Organization(name="Org", reporting_currency="RMB")
    db_session.add(org)
    db_session.flush()
    sup = Supplier(org_id=org.id, vendor_code="SDD201", name="测试供应商")
    db_session.add(sup)
    db_session.flush()
    # Manual cached mapping — bypasses header detection and the AI mapper.
    db_session.add(SupplierColumnMapping(
        supplier_id=sup.id, column_map=COLUMN_MAP, source="manual",
        header_row=0, needs_review=False,
    ))
    db_session.commit()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(CSV)
        path = f.name

    try:
        result = asyncio.run(ingest_supplier_statement(
            file_path=path, supplier_id=sup.id, period="2026-03", db=db_session,
        ))
    finally:
        Path(path).unlink(missing_ok=True)

    assert result.status == "success", result.errors
    assert result.rows_ingested == 2

    lines = db_session.query(StatementLineItem).all()
    assert len(lines) == 2
    # No phantom totals line: every ingested row names a PO.
    assert all(l.po_number and l.po_number.lower() not in ("nan", "none")
               for l in lines)
    assert not any(l.quantity == 2130601 for l in lines)
