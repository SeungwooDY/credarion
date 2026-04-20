"""Tests for invoice processing API endpoints."""
from __future__ import annotations

import io
import json
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.invoicing.ocr_extractor import InvoiceExtractionResult
from app.main import app
from app.models import Invoice, InvoiceLineItem, Organization, Supplier


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_session():
    """In-memory SQLite database for testing."""
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
    from sqlalchemy.pool import StaticPool

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    @compiles(PG_UUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):
        return "VARCHAR(36)"

    import sqlite3
    sqlite3.register_adapter(uuid.UUID, lambda u: str(u))
    sqlite3.register_converter("UUID", lambda b: uuid.UUID(b.decode()))

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def org(db_session: Session) -> Organization:
    o = Organization(name="Test Org", reporting_currency="RMB")
    db_session.add(o)
    db_session.commit()
    return o


@pytest.fixture
def supplier(db_session: Session, org: Organization) -> Supplier:
    s = Supplier(
        org_id=org.id,
        vendor_code="SDD201",
        name="奥雄电子有限公司",
    )
    db_session.add(s)
    db_session.commit()
    return s


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client with DB session override."""
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def upload_dir():
    """Temporary upload directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _create_invoice(db: Session, org_id: uuid.UUID, **overrides) -> Invoice:
    """Helper to create an invoice record directly in DB."""
    defaults = dict(
        org_id=org_id,
        status="received",
        file_url="test-file.png",
        file_type="png",
        original_filename="invoice.png",
    )
    defaults.update(overrides)
    inv = Invoice(**defaults)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


# ============================================================
# Upload Tests
# ============================================================


class TestUploadEndpoint:
    def test_upload_single_file(self, client, org, upload_dir):
        with patch("app.routers.invoices.settings") as mock_settings:
            mock_settings.invoice_upload_dir = upload_dir
            mock_settings.anthropic_api_key = "test"
            mock_settings.invoice_ocr_model = "test-model"

            resp = client.post(
                f"/api/v1/invoices/upload?org_id={org.id}",
                files=[("files", ("invoice.png", b"fake png data", "image/png"))],
            )

        assert resp.status_code == 201
        data = resp.json()
        assert len(data["invoices"]) == 1
        assert data["invoices"][0]["status"] == "received"

    def test_upload_multiple_files(self, client, org, upload_dir):
        with patch("app.routers.invoices.settings") as mock_settings:
            mock_settings.invoice_upload_dir = upload_dir
            mock_settings.anthropic_api_key = "test"
            mock_settings.invoice_ocr_model = "test-model"

            resp = client.post(
                f"/api/v1/invoices/upload?org_id={org.id}",
                files=[
                    ("files", ("inv1.png", b"png1", "image/png")),
                    ("files", ("inv2.pdf", b"pdf1", "application/pdf")),
                    ("files", ("inv3.jpg", b"jpg1", "image/jpeg")),
                ],
            )

        assert resp.status_code == 201
        assert len(resp.json()["invoices"]) == 3

    def test_upload_rejects_unsupported_type(self, client, org, upload_dir):
        with patch("app.routers.invoices.settings") as mock_settings:
            mock_settings.invoice_upload_dir = upload_dir

            resp = client.post(
                f"/api/v1/invoices/upload?org_id={org.id}",
                files=[("files", ("doc.bmp", b"data", "image/bmp"))],
            )

        assert resp.status_code == 400


# ============================================================
# Extract Tests
# ============================================================


class TestExtractEndpoint:
    def test_extract_success(self, client, db_session, org, supplier, upload_dir):
        inv = _create_invoice(db_session, org.id)

        extraction_result = InvoiceExtractionResult(
            status="success",
            fields={
                "supplier_name": "奥雄电子有限公司",
                "invoice_number": "FP-2026-001",
                "invoice_date": "2026-03-15",
                "subtotal": 10000.00,
                "vat_rate": 13,
                "vat_amount": 1300.00,
                "total_amount": 11300.00,
                "currency": "RMB",
            },
            line_items=[
                {
                    "description": "电容器",
                    "quantity": 5000,
                    "unit_price": 2.00,
                    "amount": 10000.00,
                    "po_number": "PO-428759",
                    "material_number": None,
                }
            ],
            field_confidences={
                "supplier_name": 0.95,
                "invoice_number": 0.98,
                "invoice_date": 0.92,
                "subtotal": 0.90,
                "vat_rate": 0.99,
                "vat_amount": 0.88,
                "total_amount": 0.93,
                "currency": 0.99,
            },
            overall_confidence=0.88,
            raw_response={"test": True},
        )

        with (
            patch("app.routers.invoices.settings") as mock_settings,
            patch("app.routers.invoices.extract_invoice", new_callable=AsyncMock) as mock_extract,
        ):
            mock_settings.invoice_upload_dir = upload_dir
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.invoice_ocr_model = "test-model"
            mock_extract.return_value = extraction_result

            resp = client.post(f"/api/v1/invoices/{inv.id}/extract")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "extracted"
        assert data["invoice_number"] == "FP-2026-001"
        assert data["supplier_name_extracted"] == "奥雄电子有限公司"
        assert data["supplier_id"] == str(supplier.id)  # matched!
        assert len(data["line_items"]) == 1
        assert data["extraction_confidence"] == 0.88

    def test_extract_not_found(self, client):
        fake_id = uuid.uuid4()
        with patch("app.routers.invoices.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test"
            resp = client.post(f"/api/v1/invoices/{fake_id}/extract")
        assert resp.status_code == 404

    def test_extract_wrong_status(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, status="approved")
        with patch("app.routers.invoices.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test"
            resp = client.post(f"/api/v1/invoices/{inv.id}/extract")
        assert resp.status_code == 400

    def test_extract_no_api_key(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id)
        with patch("app.routers.invoices.settings") as mock_settings:
            mock_settings.anthropic_api_key = None
            resp = client.post(f"/api/v1/invoices/{inv.id}/extract")
        assert resp.status_code == 503


# ============================================================
# List / Filter / Pagination Tests
# ============================================================


class TestListEndpoint:
    def test_list_invoices(self, client, db_session, org):
        _create_invoice(db_session, org.id, status="received")
        _create_invoice(db_session, org.id, status="extracted")

        resp = client.get(f"/api/v1/invoices/?org_id={org.id}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_filter_by_status(self, client, db_session, org):
        _create_invoice(db_session, org.id, status="received")
        _create_invoice(db_session, org.id, status="extracted")

        resp = client.get(f"/api/v1/invoices/?org_id={org.id}&status=extracted")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "extracted"

    def test_filter_needs_review(self, client, db_session, org):
        _create_invoice(db_session, org.id, needs_review=True)
        _create_invoice(db_session, org.id, needs_review=False)

        resp = client.get(f"/api/v1/invoices/?org_id={org.id}&needs_review=true")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_pagination(self, client, db_session, org):
        for _ in range(5):
            _create_invoice(db_session, org.id)

        resp = client.get(f"/api/v1/invoices/?org_id={org.id}&limit=2&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        resp2 = client.get(f"/api/v1/invoices/?org_id={org.id}&limit=2&offset=2")
        assert resp2.status_code == 200
        assert len(resp2.json()) == 2


# ============================================================
# Detail / Update Tests
# ============================================================


class TestDetailEndpoint:
    def test_get_invoice(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, invoice_number="INV-001")
        resp = client.get(f"/api/v1/invoices/{inv.id}")
        assert resp.status_code == 200
        assert resp.json()["invoice_number"] == "INV-001"

    def test_get_not_found(self, client):
        resp = client.get(f"/api/v1/invoices/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestUpdateEndpoint:
    def test_update_fields(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id)
        resp = client.put(
            f"/api/v1/invoices/{inv.id}",
            json={"invoice_number": "CORRECTED-001", "total_amount": "9999.99"},
        )
        assert resp.status_code == 200
        assert resp.json()["invoice_number"] == "CORRECTED-001"

    def test_update_triggers_supplier_match(self, client, db_session, org, supplier):
        inv = _create_invoice(db_session, org.id)
        resp = client.put(
            f"/api/v1/invoices/{inv.id}",
            json={"supplier_name_extracted": "奥雄电子有限公司"},
        )
        assert resp.status_code == 200
        assert resp.json()["supplier_id"] == str(supplier.id)


# ============================================================
# Status Transition Tests
# ============================================================


class TestStatusTransitions:
    def test_valid_transition_received_to_extracted(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, status="received")
        resp = client.put(f"/api/v1/invoices/{inv.id}/status", json={"status": "extracted"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "extracted"

    def test_valid_transition_extracted_to_approved(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, status="extracted")
        resp = client.put(f"/api/v1/invoices/{inv.id}/status", json={"status": "approved"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_valid_transition_approved_to_paid(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, status="approved")
        resp = client.put(f"/api/v1/invoices/{inv.id}/status", json={"status": "paid"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "paid"

    def test_invalid_transition_received_to_paid(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, status="received")
        resp = client.put(f"/api/v1/invoices/{inv.id}/status", json={"status": "paid"})
        assert resp.status_code == 400

    def test_invalid_transition_paid_to_received(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id, status="paid")
        resp = client.put(f"/api/v1/invoices/{inv.id}/status", json={"status": "received"})
        assert resp.status_code == 400


# ============================================================
# Line Item Tests
# ============================================================


class TestLineItems:
    def test_get_line_items(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id)
        li = InvoiceLineItem(
            invoice_id=inv.id,
            description="电容器",
            quantity=Decimal("5000"),
            unit_price=Decimal("2.00"),
            amount=Decimal("10000.00"),
            po_number="PO-001",
        )
        db_session.add(li)
        db_session.commit()

        resp = client.get(f"/api/v1/invoices/{inv.id}/line-items")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["description"] == "电容器"
        assert data[0]["po_number"] == "PO-001"

    def test_update_line_item(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id)
        li = InvoiceLineItem(
            invoice_id=inv.id,
            description="Original",
            quantity=Decimal("100"),
        )
        db_session.add(li)
        db_session.commit()
        db_session.refresh(li)

        resp = client.put(
            f"/api/v1/invoices/{inv.id}/line-items/{li.id}",
            json={"description": "Corrected", "po_number": "PO-NEW"},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Corrected"
        assert resp.json()["po_number"] == "PO-NEW"

    def test_update_line_item_not_found(self, client, db_session, org):
        inv = _create_invoice(db_session, org.id)
        fake_li_id = uuid.uuid4()
        resp = client.put(
            f"/api/v1/invoices/{inv.id}/line-items/{fake_li_id}",
            json={"description": "nope"},
        )
        assert resp.status_code == 404


# ============================================================
# Supplier Matcher Tests
# ============================================================


class TestSupplierMatcher:
    def test_exact_match(self, db_session, org, supplier):
        from app.invoicing.supplier_matcher import match_supplier

        result = match_supplier("奥雄电子有限公司", org.id, db_session)
        assert result == supplier.id

    def test_contains_match(self, db_session, org, supplier):
        from app.invoicing.supplier_matcher import match_supplier

        result = match_supplier("奥雄电子", org.id, db_session)
        assert result == supplier.id

    def test_reverse_contains_match(self, db_session, org, supplier):
        from app.invoicing.supplier_matcher import match_supplier

        # Extracted name is longer, contains supplier name
        result = match_supplier("深圳市奥雄电子有限公司总部", org.id, db_session)
        assert result == supplier.id

    def test_no_match(self, db_session, org, supplier):
        from app.invoicing.supplier_matcher import match_supplier

        result = match_supplier("完全不同的公司", org.id, db_session)
        assert result is None

    def test_empty_name(self, db_session, org):
        from app.invoicing.supplier_matcher import match_supplier

        assert match_supplier("", org.id, db_session) is None
        assert match_supplier("   ", org.id, db_session) is None
        assert match_supplier(None, org.id, db_session) is None
