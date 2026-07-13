"""Tenant-isolation tests for the chat context builder.

``_load_db_context`` previously listed every organization in the system and,
when ``org_id`` was null/foreign, fell back to the first org row globally —
leaking another tenant's org roster, suppliers, and mismatch details into the
assistant's context. It is now scoped to the caller's account.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Account, Organization, Supplier
from app.routers import chat


@pytest.fixture
def engine():
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

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def seeded(engine, monkeypatch):
    """Two tenants seeded; patch chat.SessionLocal to this engine."""
    Session = sessionmaker(bind=engine)
    db = Session()

    def _make(name: str) -> dict:
        acct = Account(name=name, plan="growth", subscription_status="active")
        db.add(acct)
        db.flush()
        org = Organization(name=f"{name}-Org", reporting_currency="RMB", account_id=acct.id)
        db.add(org)
        db.flush()
        db.add(Supplier(org_id=org.id, vendor_code=f"V-{name}", name=f"{name}-Supplier"))
        db.commit()
        return {"account_id": acct.id, "org_id": org.id}

    a = _make("acctA")
    b = _make("acctB")
    db.close()

    monkeypatch.setattr(chat, "SessionLocal", Session)
    return a, b


def test_context_scoped_to_account(seeded):
    a, b = seeded
    ctx = chat._load_db_context(None, a["account_id"], is_superuser=False)
    assert "acctA-Org" in ctx
    assert "acctA-Supplier" in ctx
    # Nothing from the other tenant may leak.
    assert "acctB-Org" not in ctx
    assert "acctB-Supplier" not in ctx


def test_foreign_org_id_cannot_select_other_tenant(seeded):
    a, b = seeded
    # Account A passes Account B's org id — must NOT load B's data.
    ctx = chat._load_db_context(str(b["org_id"]), a["account_id"], is_superuser=False)
    assert "acctB-Org" not in ctx
    assert "acctB-Supplier" not in ctx
    assert "Active organization: acctA-Org" in ctx


def test_superuser_sees_all_orgs(seeded):
    a, b = seeded
    ctx = chat._load_db_context(None, a["account_id"], is_superuser=True)
    assert "acctA-Org" in ctx
    assert "acctB-Org" in ctx
