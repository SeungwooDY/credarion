"""Shared supplier-name normalization and matching.

Single source of truth for turning a free-text supplier name (scraped from a
statement letterhead or OCR'd off an invoice) into a Supplier row. Previously
this logic was duplicated — and subtly different — in the statements router and
the invoicing supplier_matcher, which let the same statement bind to different
suppliers depending on the entry point.

Matching precedence (see match_supplier):
  1. Learned alias           — an exact (normalized) hit on a saved alias
  2. Normalized-exact        — the names are equal once normalized
  3. Overlap-scored substring — one normalized name contains the other

Ambiguity is treated as failure, not a coin-flip: if two different suppliers
score equally (e.g. an extracted generic tail like "智能科技有限公司" that is a
substring of several companies), match_supplier returns None so the caller can
force a manual pick instead of silently binding to the wrong supplier — the bug
that mis-bound 沃福（宁波）… onto 广东诚博….
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.models import Supplier, SupplierAlias

# Full-width → half-width for characters that commonly differ between how a
# supplier prints its own name and how the buyer's ERP records it.
_FULLWIDTH_MAP = {
    "（": "(",
    "）": ")",
    "，": ",",
    "、": ",",
    "　": " ",  # ideographic space
    "：": ":",
    "．": ".",
}
_FULLWIDTH_TABLE = {ord(k): v for k, v in _FULLWIDTH_MAP.items()}

# Excel/CSV artifacts that leak into names (e.g. a literal carriage return
# encoded as _x000D_ by openpyxl) and stray bracketed qualifiers that carry no
# identity ("(个体工商户)", "(13%)").
_ARTIFACT_RE = re.compile(r"_x000d_", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_supplier_name(name: str | None) -> str:
    """Normalize a supplier name for comparison.

    Trims, strips Excel artifacts, folds full-width punctuation to half-width,
    collapses whitespace, and casefolds. Returns "" for blank input.
    """
    if not name:
        return ""
    s = str(name)
    s = _ARTIFACT_RE.sub("", s)
    s = s.translate(_FULLWIDTH_TABLE)
    s = _WHITESPACE_RE.sub("", s)  # Chinese names carry no meaningful spaces
    return s.strip().casefold()


def _overlap_score(a: str, b: str) -> int:
    """Substring-overlap score between two normalized names.

    Only scores when one is contained in the other; the score is the length of
    the shorter (contained) string. 0 means no containment relationship.
    """
    if not a or not b:
        return 0
    if a in b or b in a:
        return min(len(a), len(b))
    return 0


def match_supplier(
    extracted_name: str | None, org_id: uuid.UUID, db: Session
) -> Supplier | None:
    """Resolve a free-text supplier name to a Supplier, or None if unsure.

    Returns None when nothing matches OR when the best match is ambiguous
    (two different suppliers tie), so the caller can require a manual choice.
    """
    norm = normalize_supplier_name(extracted_name)
    if not norm:
        return None

    # 1. Learned alias (exact on normalized alias).
    alias = (
        db.query(SupplierAlias)
        .filter(
            SupplierAlias.org_id == org_id,
            SupplierAlias.normalized_alias == norm,
        )
        .first()
    )
    if alias is not None:
        supplier = db.get(Supplier, alias.supplier_id)
        if supplier is not None:
            return supplier

    suppliers = db.query(Supplier).filter(Supplier.org_id == org_id).all()
    norm_by_id: dict[uuid.UUID, str] = {
        s.id: normalize_supplier_name(s.name) for s in suppliers
    }

    # 2. Normalized-exact match.
    exact = [s for s in suppliers if norm_by_id[s.id] == norm]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None  # duplicate names — ambiguous, force manual pick

    # 3. Overlap-scored substring. Ambiguity (a tie at the best score across
    #    distinct suppliers) resolves to None rather than an arbitrary guess.
    scored = [
        (score, s)
        for s in suppliers
        if (score := _overlap_score(norm, norm_by_id[s.id])) > 0
    ]
    if not scored:
        return None

    best = max(score for score, _ in scored)
    winners = [s for score, s in scored if score == best]
    if len(winners) == 1:
        return winners[0]
    return None


def match_supplier_id(
    extracted_name: str | None, org_id: uuid.UUID, db: Session
) -> uuid.UUID | None:
    """Convenience wrapper returning the matched supplier's id (or None)."""
    supplier = match_supplier(extracted_name, org_id, db)
    return supplier.id if supplier is not None else None


def record_supplier_alias(
    alias_name: str | None, supplier_id: uuid.UUID, org_id: uuid.UUID, db: Session
) -> None:
    """Remember that `alias_name` refers to `supplier_id` for this org.

    No-ops when the alias is blank or already normalizes to the supplier's own
    name. Idempotent: re-pointing an existing alias just updates its target.
    Does not commit — the caller owns the transaction.
    """
    norm = normalize_supplier_name(alias_name)
    if not norm:
        return
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        return
    if normalize_supplier_name(supplier.name) == norm:
        return  # nothing learned — already an exact match

    existing = (
        db.query(SupplierAlias)
        .filter(
            SupplierAlias.org_id == org_id,
            SupplierAlias.normalized_alias == norm,
        )
        .first()
    )
    if existing is not None:
        existing.supplier_id = supplier_id
        return
    db.add(
        SupplierAlias(
            org_id=org_id,
            supplier_id=supplier_id,
            alias_name=(alias_name or "").strip(),
            normalized_alias=norm,
        )
    )
