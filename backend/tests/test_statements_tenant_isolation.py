"""Tenant-isolation tests for the statement column-mapping endpoints.

Before the fix, ``GET /mappings/{supplier_id}`` and ``PUT /mappings/{mapping_id}``
performed no account ownership check, letting any authenticated customer read or
overwrite another tenant's ingestion mapping. These tests run as Account A's
non-superuser and assert Account B's mapping is neither readable nor mutable.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.auth_deps import get_current_user
from app.db import Base, get_db
from app.main import app
from app.models import (
    Account,
    Organization,
    Supplier,
    SupplierColumnMapping,
    User,
)


@pytest.fixture
def db_session():
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


def _make_tenant(db: Session, name: str) -> dict:
    account = Account(name=name, plan="growth", subscription_status="active")
    db.add(account)
    db.flush()
    org = Organization(name=f"{name} Org", reporting_currency="RMB", account_id=account.id)
    db.add(org)
    db.flush()
    supplier = Supplier(org_id=org.id, vendor_code=f"V-{name}", name=f"{name} Supplier")
    db.add(supplier)
    db.flush()
    mapping = SupplierColumnMapping(
        supplier_id=supplier.id,
        column_map={"po_number": "PO", "amount": "Amount"},
        source="manual",
        header_row=0,
        needs_review=False,
    )
    db.add(mapping)
    db.flush()
    user = User(
        account_id=account.id, email=f"user@{name}.test", hashed_password="x",
        full_name=f"{name} User", is_active=True, is_superuser=False, role="admin",
    )
    user.account = account
    db.add(user)
    db.commit()
    return {"supplier": supplier, "mapping": mapping, "user": user}


@pytest.fixture
def two_tenants(db_session: Session):
    return _make_tenant(db_session, "acct-a"), _make_tenant(db_session, "acct-b")


@pytest.fixture
def client_as_a(db_session: Session, two_tenants):
    a, _ = two_tenants

    def _override_get_db():
        yield db_session

    def _override_user():
        return a["user"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_own_mapping_readable(client_as_a, two_tenants):
    a, _ = two_tenants
    resp = client_as_a.get(f"/api/v1/statements/mappings/{a['supplier'].id}")
    assert resp.status_code == 200
    assert resp.json()["supplier_id"] == str(a["supplier"].id)


def test_cross_tenant_get_mapping_blocked(client_as_a, two_tenants):
    _, b = two_tenants
    resp = client_as_a.get(f"/api/v1/statements/mappings/{b['supplier'].id}")
    assert resp.status_code in (403, 404)


def test_cross_tenant_update_mapping_blocked(client_as_a, two_tenants):
    _, b = two_tenants
    resp = client_as_a.put(
        f"/api/v1/statements/mappings/{b['mapping'].id}",
        json={"column_map": {"po_number": "HIJACKED"}},
    )
    assert resp.status_code in (403, 404)
    assert b["mapping"].column_map == {"po_number": "PO", "amount": "Amount"}
