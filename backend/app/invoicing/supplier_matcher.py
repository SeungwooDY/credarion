"""Match OCR-extracted supplier names to existing suppliers in the database."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Supplier


def match_supplier(extracted_name: str, org_id: uuid.UUID, db: Session) -> uuid.UUID | None:
    """Attempt to match an extracted supplier name to a known supplier.

    Matching strategy:
    1. Exact match on Supplier.name
    2. Contains match (extracted name in supplier name or vice versa)

    Returns the supplier UUID or None.
    """
    if not extracted_name or not extracted_name.strip():
        return None

    extracted_name = extracted_name.strip()

    suppliers = db.query(Supplier).filter(Supplier.org_id == org_id).all()

    # 1. Exact match
    for s in suppliers:
        if s.name == extracted_name:
            return s.id

    # 2. Contains match
    for s in suppliers:
        if extracted_name in s.name or s.name in extracted_name:
            return s.id

    return None
