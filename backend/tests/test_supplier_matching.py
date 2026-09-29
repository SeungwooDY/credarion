"""Tests for supplier-name extraction, normalization, and matching.

Regression coverage for the 2026-09-29 mis-binding: a statement for
沃福（宁波）智能科技有限公司 was silently bound to 广东诚博智能科技有限公司 because
full-width brackets truncated the detected name to the generic tail
"智能科技有限公司", which substring-matched multiple suppliers and resolved to an
arbitrary (wrong) one. See app/supplier_matching.py and _extract_supplier_name.
"""
from __future__ import annotations

import uuid

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Organization, Supplier, SupplierAlias
from app.routers.statements import _extract_supplier_name
from app.supplier_matching import (
    match_supplier,
    normalize_supplier_name,
    record_supplier_alias,
)


@pytest.fixture
def db_session():
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
    import sqlite3

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):
        return "JSON"

    @compiles(PG_UUID, "sqlite")
    def _uuid(type_, compiler, **kw):
        return "VARCHAR(36)"

    engine = create_engine("sqlite:///:memory:", echo=False)
    sqlite3.register_adapter(uuid.UUID, lambda u: str(u))
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


def _supplier(db: Session, org: Organization, code: str, name: str) -> Supplier:
    s = Supplier(org_id=org.id, vendor_code=code, name=name)
    db.add(s)
    db.commit()
    return s


# ── Extraction (regression for the truncation bug) ──────────────────────


class TestExtraction:
    def _extract(self, *header_rows: str) -> str | None:
        # Build a raw frame with the given rows above a header at index len().
        rows = [[cell] for cell in header_rows] + [["物料号"], ["x"]]
        df = pd.DataFrame(rows)
        return _extract_supplier_name(df, header_row=len(header_rows))

    def test_fullwidth_brackets_do_not_truncate(self):
        # The exact bug: must return the whole name, not "智能科技有限公司".
        assert self._extract("沃福（宁波）智能科技有限公司") == "沃福（宁波）智能科技有限公司"

    def test_halfwidth_brackets_kept(self):
        assert self._extract("必佳科技(深圳)有限公司") == "必佳科技(深圳)有限公司"

    def test_plain_name(self):
        assert self._extract("广东诚博智能科技有限公司") == "广东诚博智能科技有限公司"

    def test_supply_unit_label(self):
        assert self._extract("供货单位：沃福（宁波）智能科技有限公司") == (
            "沃福（宁波）智能科技有限公司"
        )


# ── Normalization ───────────────────────────────────────────────────────


class TestNormalization:
    def test_fullwidth_to_halfwidth_and_artifacts(self):
        assert normalize_supplier_name("沃福（宁波）智能科技有限公司_x000D_") == (
            "沃福(宁波)智能科技有限公司"
        )

    def test_whitespace_collapsed_and_casefolded(self):
        assert normalize_supplier_name("  ABC （X）  Co ") == "abc(x)co"

    def test_blank(self):
        assert normalize_supplier_name(None) == ""
        assert normalize_supplier_name("   ") == ""


# ── Matching ──────────────────────────────────────────────────────────────


class TestMatching:
    def test_exact_after_normalization(self, db_session: Session, org: Organization):
        wf = _supplier(db_session, org, "NWE202", "沃福（宁波）智能科技有限公司")
        # Half-width brackets in the query still resolve to the full-width row.
        m = match_supplier("沃福(宁波)智能科技有限公司", org.id, db_session)
        assert m is not None and m.id == wf.id

    def test_generic_tail_is_ambiguous_not_a_wrong_guess(
        self, db_session: Session, org: Organization
    ):
        # Two suppliers share the tail; a bare tail must NOT bind to either.
        _supplier(db_session, org, "NWE202", "沃福（宁波）智能科技有限公司")
        _supplier(db_session, org, "CBZN01", "广东诚博智能科技有限公司")
        assert match_supplier("智能科技有限公司", org.id, db_session) is None

    def test_full_name_resolves_despite_shared_tail(
        self, db_session: Session, org: Organization
    ):
        wf = _supplier(db_session, org, "NWE202", "沃福（宁波）智能科技有限公司")
        _supplier(db_session, org, "CBZN01", "广东诚博智能科技有限公司")
        m = match_supplier("沃福（宁波）智能科技有限公司", org.id, db_session)
        assert m is not None and m.id == wf.id

    def test_no_match_returns_none(self, db_session: Session, org: Organization):
        _supplier(db_session, org, "AAA001", "完全不同的公司有限公司")
        assert match_supplier("某某电子有限公司", org.id, db_session) is None

    def test_blank_returns_none(self, db_session: Session, org: Organization):
        assert match_supplier("", org.id, db_session) is None


# ── Aliases ───────────────────────────────────────────────────────────────


class TestAliases:
    def test_alias_round_trip(self, db_session: Session, org: Organization):
        # 沃福 statement letterhead differs from the ERP name; learn it once...
        wf = _supplier(db_session, org, "NWE202", "沃福智能科技有限公司")
        record_supplier_alias("沃福（宁波）智能科技有限公司", wf.id, org.id, db_session)
        db_session.commit()
        # ...then a future upload with that letterhead resolves immediately.
        m = match_supplier("沃福（宁波）智能科技有限公司", org.id, db_session)
        assert m is not None and m.id == wf.id

    def test_alias_wins_over_ambiguous_tail(
        self, db_session: Session, org: Organization
    ):
        wf = _supplier(db_session, org, "NWE202", "沃福（宁波）智能科技有限公司")
        _supplier(db_session, org, "CBZN01", "广东诚博智能科技有限公司")
        record_supplier_alias("智能科技有限公司", wf.id, org.id, db_session)
        db_session.commit()
        m = match_supplier("智能科技有限公司", org.id, db_session)
        assert m is not None and m.id == wf.id

    def test_exact_name_is_not_stored_as_alias(
        self, db_session: Session, org: Organization
    ):
        wf = _supplier(db_session, org, "NWE202", "沃福（宁波）智能科技有限公司")
        record_supplier_alias("沃福（宁波）智能科技有限公司", wf.id, org.id, db_session)
        db_session.commit()
        assert db_session.query(SupplierAlias).count() == 0

    def test_repointing_alias_updates_target(
        self, db_session: Session, org: Organization
    ):
        a = _supplier(db_session, org, "AAA001", "甲公司有限公司")
        b = _supplier(db_session, org, "BBB001", "乙公司有限公司")
        record_supplier_alias("某letterhead名有限公司", a.id, org.id, db_session)
        db_session.commit()
        record_supplier_alias("某letterhead名有限公司", b.id, org.id, db_session)
        db_session.commit()
        assert db_session.query(SupplierAlias).count() == 1
        m = match_supplier("某letterhead名有限公司", org.id, db_session)
        assert m is not None and m.id == b.id
