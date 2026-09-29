"""Match OCR-extracted supplier names to existing suppliers in the database.

Thin wrapper over app.supplier_matching so invoice matching and statement
matching share one normalization + resolution path (aliases, full-width folding,
ambiguity → no-match). See app/supplier_matching.py for the strategy.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.supplier_matching import match_supplier_id


def match_supplier(extracted_name: str, org_id: uuid.UUID, db: Session) -> uuid.UUID | None:
    """Resolve an OCR-extracted supplier name to a known supplier's UUID.

    Returns the supplier UUID, or None when there is no confident match.
    """
    return match_supplier_id(extracted_name, org_id, db)
